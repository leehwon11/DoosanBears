"""
두산 베어스 분석 웹사이트 - Claude AI 분석 모듈
================================================
경기 종합 평가 + 선수 개인 평가를 Claude API로 생성

설치:
    pip install anthropic python-dotenv

.env 파일에 추가:
    ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
"""

import os
from anthropic import Anthropic
from dotenv import load_dotenv
from database import save_ai_report, get_game_detail

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _call_claude(prompt: str) -> str:
    """Claude API 호출 공통 함수."""
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def analyze_game(game_id: str) -> str:
    """경기 전체 흐름을 분석해서 종합 평가 리포트를 생성합니다."""
    detail = get_game_detail(game_id)
    game   = detail.get("game", {})

    if not game:
        return "경기 데이터가 없습니다."

    batters = detail.get("batters", [])
    batter_lines = "\n".join([
        f"  {b['name']}: {b['ab']}타수 {b['h']}안타 {b['hr']}홈런 {b['rbi']}타점 {b['bb']}볼넷 {b['so']}삼진"
        for b in batters
    ])

    pitchers = detail.get("pitchers", [])
    pitcher_lines = "\n".join([
        f"  {p['name']} ({p['result']}): {p['ip']}이닝 {p['er']}자책 {p['so']}삼진 {p['bb']}볼넷"
        for p in pitchers
    ])

    innings = detail.get("innings", [])
    doosan_inn   = sorted([i for i in innings if i["team"] == "doosan"],   key=lambda x: x["inning"])
    opponent_inn = sorted([i for i in innings if i["team"] == "opponent"], key=lambda x: x["inning"])
    doosan_scores   = " ".join([str(i["score"]) for i in doosan_inn])
    opponent_scores = " ".join([str(i["score"]) for i in opponent_inn])

    opponent = game['away_team'] if game['home_team'] == '두산' else game['home_team']

    prompt = f"""당신은 KBO 두산 베어스 전문 야구 분석가입니다.
아래 오늘 경기 데이터를 바탕으로 팬들이 읽기 좋은 경기 종합 평가를 작성해주세요.

===== 경기 정보 =====
날짜: {game['date']}
두산 베어스 vs {opponent}
최종 스코어: {game['home_team']} {game['home_score']} : {game['away_score']} {game['away_team']}
결과: {game['result']}

이닝별 점수:
  두산:   {doosan_scores}
  상대팀: {opponent_scores}

===== 타자 기록 =====
{batter_lines}

===== 투수 기록 =====
{pitcher_lines}

===== 작성 지침 =====
- 3~4문단 분량으로 작성
- 경기 흐름 요약 → 타선 평가 → 투수진 평가 → 총평 순서
- 잘한 점과 아쉬운 점을 균형 있게 서술
- 팬 입장에서 공감할 수 있는 따뜻한 톤으로 작성
- 전문 용어는 쉽게 풀어서 설명
"""

    result = _call_claude(prompt)
    save_ai_report(game_id, "game", result)
    print(f"경기 종합 평가 저장 완료: {game_id}")
    return result


def analyze_player(game_id: str, player_name: str) -> str:
    """특정 선수의 오늘 경기 기록을 분석해서 개인 평가를 생성합니다."""
    detail   = get_game_detail(game_id)
    game     = detail.get("game", {})
    batters  = detail.get("batters", [])
    pitchers = detail.get("pitchers", [])

    player_data = next((b for b in batters  if b["name"] == player_name), None)
    is_pitcher  = False
    if not player_data:
        player_data = next((p for p in pitchers if p["name"] == player_name), None)
        is_pitcher  = True

    if not player_data:
        return f"{player_name} 선수의 기록을 찾을 수 없습니다."

    opponent = game.get('away_team') if game.get('home_team') == '두산' else game.get('home_team')

    if not is_pitcher:
        prompt = f"""당신은 KBO 두산 베어스 전문 야구 분석가입니다.
아래 선수의 오늘 경기 기록을 바탕으로 팬들이 읽기 좋은 개인 평가를 작성해주세요.

===== 선수 정보 =====
이름: {player_name} | 포지션: {player_data.get('position', '알 수 없음')}
날짜: {game.get('date', '')} | 상대팀: {opponent} | 경기 결과: {game.get('result', '')}

===== 오늘 기록 =====
타수: {player_data['ab']}  안타: {player_data['h']}  홈런: {player_data['hr']}
타점: {player_data['rbi']}  득점: {player_data['r']}
볼넷: {player_data['bb']}  삼진: {player_data['so']}  타율: {player_data.get('avg', '-')}

===== 작성 지침 =====
- 2~3문단 분량
- 오늘 활약 요약 → 잘한 점 → 아쉬운 점 또는 발전 방향 순서
- 구체적인 수치를 근거로 평가
- 팬 입장에서 따뜻하고 솔직한 톤으로 작성
"""
    else:
        prompt = f"""당신은 KBO 두산 베어스 전문 야구 분석가입니다.
아래 투수의 오늘 경기 기록을 바탕으로 팬들이 읽기 좋은 개인 평가를 작성해주세요.

===== 선수 정보 =====
이름: {player_name}
날짜: {game.get('date', '')} | 상대팀: {opponent} | 경기 결과: {game.get('result', '')}

===== 오늘 기록 =====
결과: {player_data.get('result', '-')}  이닝: {player_data.get('ip', '-')}
피안타: {player_data['h']}  피홈런: {player_data['hr']}
볼넷: {player_data['bb']}  삼진: {player_data['so']}
자책점: {player_data['er']}  평균자책점: {player_data.get('era', '-')}

===== 작성 지침 =====
- 2~3문단 분량
- 오늘 피칭 흐름 요약 → 잘한 점 → 아쉬운 점 또는 발전 방향 순서
- 구체적인 수치를 근거로 평가
- 팬 입장에서 따뜻하고 솔직한 톤으로 작성
"""

    result = _call_claude(prompt)
    save_ai_report(game_id, "player", result, player_name)
    print(f"선수 평가 저장 완료: {player_name} ({game_id})")
    return result


def analyze_all(game_id: str):
    """
    경기 종합 평가 + 전 선수 개인 평가를 한 번에 실행합니다.
    scheduler.py의 run_crawl_job()에서 크롤링 후 이 함수를 호출해요.
    """
    print(f"\n=== AI 분석 시작: {game_id} ===")

    print("[1] 경기 종합 평가 생성 중...")
    analyze_game(game_id)

    detail   = get_game_detail(game_id)
    batters  = detail.get("batters", [])
    pitchers = detail.get("pitchers", [])

    print(f"[2] 선수 개인 평가 생성 중... (타자 {len(batters)}명, 투수 {len(pitchers)}명)")
    for player in batters + pitchers:
        name = player.get("name")
        if name:
            analyze_player(game_id, name)

    print("=== AI 분석 완료 ===\n")


if __name__ == "__main__":
    test_game_id = "20260424OBHH02"
    print(analyze_game(test_game_id))
