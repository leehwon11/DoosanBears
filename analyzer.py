"""
두산 베어스 분석 웹사이트 - Claude AI 분석 모듈
=================================================
설치:
    pip install anthropic python-dotenv

.env 파일에 추가:
    ANTHROPIC_API_KEY=sk-ant-여기에키입력
"""

import os
import time
import anthropic
from dotenv import load_dotenv
from database import save_ai_report, get_game_detail

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _call_claude(prompt: str) -> str:
    """Claude API 호출. 오류 시 재시도."""
    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except anthropic.RateLimitError as e:
            wait = (attempt + 1) * 15
            print(f"    API 한도 초과 — {wait}초 후 재시도...")
            time.sleep(wait)
        except Exception as e:
            raise e


def analyze_game(game_id: str) -> str:
    """경기 전체 흐름 종합 평가"""
    detail = get_game_detail(game_id)
    game   = detail.get("game", {})
    if not game:
        return "경기 데이터가 없습니다."

    batters  = detail.get("batters", [])
    pitchers = detail.get("pitchers", [])

    batter_lines = "\n".join([
        f"  {b['name']} ({b.get('position','')}): {b['ab']}타수 {b['h']}안타 {b['rbi']}타점 {b['bb']}볼넷 타율{b.get('avg','')}"
        for b in batters
    ])
    pitcher_lines = "\n".join([
        f"  {p['name']} ({p.get('result','-')}): {p['ip']}이닝 {p['er']}자책 {p['so']}삼진 ERA {p.get('era','')}"
        for p in pitchers
    ])

    innings      = detail.get("innings", [])
    doosan_inn   = sorted([i for i in innings if i["team"] == "doosan"],   key=lambda x: x["inning"])
    opponent_inn = sorted([i for i in innings if i["team"] == "opponent"], key=lambda x: x["inning"])
    doosan_scores   = " ".join([str(i["score"]) for i in doosan_inn])
    opponent_scores = " ".join([str(i["score"]) for i in opponent_inn])
    opponent = game.get('away_team') if game.get('home_team') == '두산' else game.get('home_team')

    prompt = f"""당신은 KBO 두산 베어스 전문 야구 분석가입니다.
아래 경기 데이터를 바탕으로 팬들이 읽기 좋은 경기 종합 평가를 작성해주세요.

===== 경기 정보 =====
날짜: {game.get('date','')}
두산 베어스 vs {opponent}
최종 스코어: {game.get('home_team','')} {game.get('home_score',0)} : {game.get('away_score',0)} {game.get('away_team','')}
결과: {game.get('result','')}
이닝별: 두산 {doosan_scores} / 상대 {opponent_scores}

===== 타자 기록 =====
{batter_lines}

===== 투수 기록 =====
{pitcher_lines}

===== 작성 지침 =====
- 3~4문단 분량
- 경기 흐름 요약 → 타선 평가 → 투수진 평가 → 총평 순서
- 잘한 점과 아쉬운 점을 균형 있게 서술
- 팬 입장에서 따뜻한 톤으로 작성
"""
    result = _call_claude(prompt)
    save_ai_report(game_id, "game", result)
    print(f"경기 종합 평가 저장 완료: {game_id}")
    return result


def analyze_player(game_id: str, player_name: str) -> str:
    """선수 개인 평가"""
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
아래 타자의 오늘 경기 기록을 바탕으로 팬들이 읽기 좋은 개인 평가를 작성해주세요.

이름: {player_name} | 포지션: {player_data.get('position','')}
날짜: {game.get('date','')} | 상대: {opponent} | 결과: {game.get('result','')}
타수: {player_data['ab']} 안타: {player_data['h']} 타점: {player_data['rbi']} 볼넷: {player_data['bb']} 타율: {player_data.get('avg','-')}

2~3문단, 오늘 활약 요약 → 잘한 점 → 발전 방향, 팬 입장에서 따뜻하고 솔직하게 작성해주세요.
"""
    else:
        prompt = f"""당신은 KBO 두산 베어스 전문 야구 분석가입니다.
아래 투수의 오늘 경기 기록을 바탕으로 팬들이 읽기 좋은 개인 평가를 작성해주세요.

이름: {player_name}
날짜: {game.get('date','')} | 상대: {opponent} | 결과: {game.get('result','')}
결과: {player_data.get('result','-')} 이닝: {player_data.get('ip','-')} 피안타: {player_data['h']} 볼넷: {player_data['bb']} 삼진: {player_data['so']} 자책: {player_data['er']} ERA: {player_data.get('era','-')}

2~3문단, 오늘 피칭 흐름 요약 → 잘한 점 → 발전 방향, 팬 입장에서 따뜻하고 솔직하게 작성해주세요.
"""

    result = _call_claude(prompt)
    save_ai_report(game_id, "player", result, player_name)
    print(f"선수 평가 저장 완료: {player_name} ({game_id})")
    return result


def analyze_all(game_id: str):
    """경기 종합 + 전 선수 평가"""
    print(f"\n=== AI 분석 시작: {game_id} ===")
    analyze_game(game_id)
    detail   = get_game_detail(game_id)
    batters  = detail.get("batters", [])
    pitchers = detail.get("pitchers", [])
    for player in batters + pitchers:
        name = player.get("name")
        if name:
            analyze_player(game_id, name)
            time.sleep(2)
    print("=== AI 분석 완료 ===\n")


if __name__ == "__main__":
    print(analyze_game("20260405HHOB0"))
