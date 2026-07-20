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

base_url = os.getenv("ANTHROPIC_BASE_URL")
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=base_url if base_url else None,
)


def _call_claude(prompt: str, max_tokens: int = 2048) -> str:
    """Claude API 호출. 오류 시 재시도. 재시도 소진 시 예외를 던짐(빈 리포트 저장 방지)."""
    last_err = None
    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except anthropic.RateLimitError as e:
            last_err = e
            wait = (attempt + 1) * 15
            print(f"    API 한도 초과 — {wait}초 후 재시도...")
            time.sleep(wait)
        except Exception as e:
            raise e
    raise RuntimeError(f"Claude API 호출 3회 재시도 후 실패: {last_err}")


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

    prompt = f"""당신은 KBO 리그 전문 전략분석원입니다. 두산 베어스의 경기 데이터를 바탕으로 객관적이고 전문적인 경기 분석 보고서를 작성하십시오.

===== 경기 정보 =====
날짜: {game.get('date','')}
두산 베어스 vs {opponent}
최종 스코어: {game.get('home_team','')} {game.get('home_score',0)} : {game.get('away_score',0)} {game.get('away_team','')}
결과: {game.get('result','')}
이닝별 득점: 두산 [{doosan_scores}] / 상대 [{opponent_scores}]

===== 타자 기록 =====
{batter_lines}

===== 투수 기록 =====
{pitcher_lines}

===== 분석 지침 =====
아래 항목을 포함한 전략 분석 보고서를 작성하십시오.

1. 경기 흐름 분석
   - 득점 이닝 패턴 및 흐름 전환 구간 파악
   - 결정적 국면(득점권 상황, 실점 장면) 지적

2. 타선 전술 평가
   - 팀 출루율 및 클러치 상황 대응력
   - 주요 타자의 기여도와 약점 노출 여부
   - 상대 투수 공략 전략의 유효성

3. 투수진 운용 평가
   - 선발 투수의 이닝 소화 효율 및 구위 안정성
   - 불펜 운용의 적절성 (타이밍, 매치업)
   - 피안타/볼넷/삼진 비율로 본 투구 내용

4. 전술적 제언
   - 다음 경기를 위한 개선 포인트
   - 상대팀 분석을 통한 대응 전략 제안

수치를 적극 인용하고, 감정적 표현보다 객관적·분석적 문체로 작성하십시오.
"""
    result = _call_claude(prompt, max_tokens=3072)
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
        prompt = f"""당신은 KBO 리그 전문 전략분석원입니다. 아래 타자의 경기 기록을 바탕으로 전문적인 선수 분석 보고서를 작성하십시오.

[선수 정보]
이름: {player_name} | 포지션: {player_data.get('position','')}
날짜: {game.get('date','')} | 상대: {opponent} | 팀 결과: {game.get('result','')}

[오늘 기록]
타수: {player_data['ab']} | 안타: {player_data['h']} | 타점: {player_data['rbi']} | 볼넷: {player_data['bb']} | 삼진: {player_data.get('so', 0)} | 타율: {player_data.get('avg','-')} | 홈런: {player_data.get('hr', 0)} | 2루타: {player_data.get('doubles', 0)} | 3루타: {player_data.get('triples', 0)}

아래 항목을 포함하여 분석 보고서를 작성하십시오.

1. 오늘 타격 내용 요약
   - 타구 결과별 분석 (안타/범타/삼진/볼넷 패턴)
   - 득점권 상황에서의 대응력

2. 강점 및 약점 분석
   - 오늘 경기에서 드러난 강점
   - 보완이 필요한 부분 (선구안, 삼진율, 장타력 등)

3. 전술적 제언
   - 다음 경기를 위한 타격 접근 방향
   - 상대 투수 유형별 대응 전략

수치를 근거로 객관적·분석적 문체로 작성하십시오. (2~3문단)
"""
    else:
        prompt = f"""당신은 KBO 리그 전문 전략분석원입니다. 아래 투수의 경기 기록을 바탕으로 전문적인 선수 분석 보고서를 작성하십시오.

[선수 정보]
이름: {player_name} | 역할: {player_data.get('role', '-')}
날짜: {game.get('date','')} | 상대: {opponent} | 팀 결과: {game.get('result','')}

[오늘 기록]
등판 결과: {player_data.get('result','-')} | 투구 이닝: {player_data.get('ip','-')} | 투구수: {player_data.get('pitch_count', '-')}
피안타: {player_data['h']} | 4사구: {player_data['bb']} | 삼진: {player_data['so']} | 실점: {player_data.get('r', '-')} | 자책: {player_data['er']} | ERA: {player_data.get('era','-')}
WHIP: {round((player_data['h'] + player_data['bb']) / float(player_data.get('ip', 1) or 1), 2) if player_data.get('ip') else '-'}

아래 항목을 포함하여 분석 보고서를 작성하십시오.

1. 오늘 피칭 내용 요약
   - 이닝별 구위 흐름 및 안정성
   - 위기 상황 발생 원인 (볼넷, 피안타 등)

2. 강점 및 약점 분석
   - 오늘 경기에서 드러난 강점 (삼진 능력, 제구력 등)
   - 보완이 필요한 부분 (4사구율, 피장타 등)

3. 전술적 제언
   - 다음 등판을 위한 투구 전략 방향
   - 불펜/선발 운용 관점에서의 활용 제안

수치를 근거로 객관적·분석적 문체로 작성하십시오. (2~3문단)
"""

    result = _call_claude(prompt, max_tokens=1536)
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
            time.sleep(1)
    print("=== AI 분석 완료 ===\n")


if __name__ == "__main__":
    print(analyze_game("20260405HHOB0"))
