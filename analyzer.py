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
from stats_utils import ip_to_outs, outs_to_ip, fmt_rate

load_dotenv()

base_url = os.getenv("ANTHROPIC_BASE_URL")
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=base_url if base_url else None,
)


# 모든 AI 분석에 공통으로 적용하는 작성 원칙 (system 프롬프트)
STYLE_GUIDE = """당신은 KBO 리그 전문 분석가로, 두산 베어스 팬 사이트에 실릴 분석 글을 씁니다.

[근거]
- 판단은 반드시 함께 주어진 기록의 수치에 근거하십시오.
- 기록에 없는 내용은 추측하거나 지어내지 마십시오. 이 사이트에는 경기 합계 기록만 있으며 타석별 상황, 득점권 성적, 구종·구속, 수비, 상대 팀 선수 기록, 부상·인터뷰 정보는 없습니다. 필요하면 "기록만으로는 알 수 없다"고 쓰십시오.
- 표본이 적으면(한두 경기, 적은 타석·이닝) 그 한계를 짧게 밝히십시오.

[독자와 문체]
- 독자는 야구를 좋아하지만 세부 지표에는 익숙하지 않은 팬입니다.
- 문체는 객관적인 분석 보고서체(~다, ~했다)로 씁니다. 과한 응원이나 비난, 감탄사는 쓰지 않습니다.
- 숫자만 나열하지 말고 그 숫자가 경기에서 무엇을 뜻하는지 풀어 쓰십시오.
- ERA, WHIP, OPS, 출루율, 장타율 같은 지표는 처음 나올 때 괄호로 짧게 뜻을 풀어 주십시오. 예: WHIP(이닝당 내보낸 주자 수, 낮을수록 좋음)
- 문장은 짧고 분명하게 씁니다.

[형식]
- 화면에 일반 텍스트로 표시되므로 마크다운(#, **, 표, 글머리 기호 -, *)을 쓰지 마십시오.
- 소제목은 "■ 소제목" 한 줄로 쓰고, 그 아래에 문단을 씁니다. 문단 사이는 한 줄 띄웁니다.
- 지시된 분량을 지키십시오."""


# 사용할 모델 (서버 환경변수 ANTHROPIC_MODEL로 바꿀 수 있음)
# claude-sonnet-4-5는 더 이상 제공되지 않아 404가 나므로 현재 Sonnet으로 교체
CLAUDE_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5-5"

# Sonnet 5.5는 기본으로 생각(thinking)을 한 뒤 답하고, 그 토큰도 max_tokens에 포함됨
# → 리포트가 중간에 잘리지 않도록 최소 16000으로 잡음
MIN_MAX_TOKENS = 16000


def _call_claude(prompt: str, max_tokens: int = 2048, system: str = STYLE_GUIDE) -> str:
    """Claude API 호출. 오류 시 재시도. 재시도 소진 시 예외를 던짐(빈 리포트 저장 방지)."""
    last_err = None
    for attempt in range(3):
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max(max_tokens, MIN_MAX_TOKENS),
                system=system,
                messages=[{"role": "user", "content": prompt}]
            )
            if message.stop_reason == "refusal":
                raise RuntimeError("AI가 이 요청에 대한 응답을 거절했어요.")
            # 응답 앞에 thinking 블록이 올 수 있으므로 text 블록만 모음
            text = "".join(b.text for b in message.content if b.type == "text").strip()
            if not text:
                raise RuntimeError(f"AI 응답이 비어 있어요 (stop_reason={message.stop_reason})")
            return text
        except anthropic.RateLimitError as e:
            last_err = e
            wait = (attempt + 1) * 15
            print(f"    API 한도 초과 — {wait}초 후 재시도...")
            time.sleep(wait)
    raise RuntimeError(f"Claude API 호출 3회 재시도 후 실패: {last_err}")


def _fmt_date(d: str) -> str:
    return f"{d[:4]}.{d[4:6]}.{d[6:8]}" if d and len(d) >= 8 else (d or "")


def _matchup(game: dict) -> dict:
    """두산 기준 경기 정보"""
    is_home = game.get("home_team") == "두산"
    return {
        "opponent": game.get("away_team") if is_home else game.get("home_team"),
        "venue": "홈" if is_home else "원정",
        "us": (game.get("home_score") if is_home else game.get("away_score")) or 0,
        "them": (game.get("away_score") if is_home else game.get("home_score")) or 0,
    }


def _batter_line(b: dict) -> str:
    extra = []
    # 득점(r)은 크롤러가 수집하지 않아 항상 0이므로 넣지 않음
    for key, label in (("doubles", "2루타"), ("triples", "3루타"), ("hr", "홈런")):
        if b.get(key):
            extra.append(f"{label} {b[key]}")
    order = f"{b['batting_order']}번 " if b.get("batting_order") else ""
    return (f"  {order}{b['name']}({b.get('position', '')}): {b['ab']}타수 {b['h']}안타 {b['rbi']}타점 "
            f"볼넷 {b['bb']} 삼진 {b.get('so', 0)}" + (" · " + " ".join(extra) if extra else "")
            + f" (시즌 타율 {b.get('avg') or '-'})")


DECISION_LABEL = {"세": "세이브", "S": "세이브", "H": "홀드"}


def _pitcher_line(p: dict) -> str:
    outs = ip_to_outs(p.get("ip"))
    whip = f"{(p['h'] + p['bb']) * 3 / outs:.2f}" if outs else "-"
    result = f" [{DECISION_LABEL.get(p['result'], p['result'])}]" if p.get("result") else ""
    return (f"  {p['name']}({p.get('role') or '-'}){result}: {p.get('ip') or '0'}이닝 "
            f"타자 {p.get('bf', 0)}명 투구수 {p.get('pitch_count') or '-'} 피안타 {p['h']} 피홈런 {p.get('hr', 0)} "
            f"4사구 {p['bb']} 삼진 {p['so']} 실점 {p.get('r', '-')} 자책 {p['er']} "
            f"(경기 WHIP {whip}, 시즌 ERA {p.get('era') or '-'})")


def analyze_game(game_id: str) -> str:
    """경기 전체 흐름 종합 평가"""
    detail = get_game_detail(game_id)
    game   = detail.get("game", {})
    if not game:
        return "경기 데이터가 없습니다."

    batters  = detail.get("batters", [])
    pitchers = detail.get("pitchers", [])
    m = _matchup(game)

    innings = detail.get("innings", [])
    doosan_inn   = [str(i["score"]) for i in sorted(innings, key=lambda x: x["inning"]) if i["team"] == "doosan"]
    opponent_inn = [str(i["score"]) for i in sorted(innings, key=lambda x: x["inning"]) if i["team"] == "opponent"]
    home_inn = doosan_inn if m["venue"] == "홈" else opponent_inn
    away_inn = opponent_inn if m["venue"] == "홈" else doosan_inn
    inning_note = " (홈팀이 앞서 마지막 회말 공격은 하지 않음)" if 0 < len(home_inn) < len(away_inn) else ""

    team_ab = sum(b["ab"] for b in batters)
    team_h  = sum(b["h"] for b in batters)
    team_hr = sum(b.get("hr", 0) for b in batters)
    team_bb = sum(b["bb"] for b in batters)
    team_so = sum(b.get("so", 0) for b in batters)
    starter = next((p for p in pitchers if p.get("role") == "선발"), pitchers[0] if pitchers else None)
    bullpen = [p for p in pitchers if p is not starter]
    bullpen_outs = sum(ip_to_outs(p.get("ip")) for p in bullpen)

    prompt = f"""두산 베어스의 아래 경기를 분석해 주십시오.

[경기 정보]
날짜: {_fmt_date(game.get('date', ''))} · {m['venue']} 경기{(' · ' + game['stadium']) if game.get('stadium') else ''}
결과: 두산 {m['us']} : {m['them']} {m['opponent']} (두산 {game.get('result', '')})
이닝별 득점 (1회부터){inning_note}
  두산: {' '.join(doosan_inn) or '-'}
  {m['opponent']}: {' '.join(opponent_inn) or '-'}

[두산 타선] 합계 {team_ab}타수 {team_h}안타 홈런 {team_hr} 볼넷 {team_bb} 삼진 {team_so}
{chr(10).join(_batter_line(b) for b in batters) or '  기록 없음'}

[두산 투수진] 선발 {starter['name'] if starter else '-'} {starter.get('ip', '-') if starter else ''}이닝 / 불펜 {len(bullpen)}명 {outs_to_ip(bullpen_outs)}이닝
{chr(10).join(_pitcher_line(p) for p in pitchers) or '  기록 없음'}

※ 상대 팀 선수 기록은 없습니다. 타자의 '시즌 타율'과 투수의 '시즌 ERA'는 이 경기 이후 시즌 누적 기록입니다.

[작성 항목]
■ 한 줄 요약: 이 경기를 한 문장으로 정리
■ 경기 흐름: 이닝별 득점으로 본 승부처 (어느 이닝에 점수가 나고 흐름이 바뀌었는지)
■ 타선: 누가 득점을 만들었는지, 팀 전체로 출루와 장타는 어땠는지
■ 마운드: 선발이 얼마나 버텼는지, 불펜이 몇 점을 막거나 내줬는지
■ 다음 경기를 위한 과제: 기록에서 드러난 개선점 1~2가지

각 항목은 2~4문장으로 쓰십시오.
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

    player_data = next((b for b in batters if b["name"] == player_name), None)
    is_pitcher  = False
    if not player_data:
        player_data = next((p for p in pitchers if p["name"] == player_name), None)
        is_pitcher  = True

    if not player_data:
        return f"{player_name} 선수의 기록을 찾을 수 없습니다."

    m = _matchup(game)
    header = (f"날짜: {_fmt_date(game.get('date', ''))} · {m['venue']} · "
              f"두산 {m['us']} : {m['them']} {m['opponent']} (두산 {game.get('result', '')})")

    if not is_pitcher:
        prompt = f"""두산 베어스 타자 {player_name}의 이 경기 활약을 분석해 주십시오.

[경기]
{header}

[{player_name} 기록]
{_batter_line(player_data)}

※ 타석별 결과(어떤 상황에서 안타·범타였는지)는 기록에 없습니다. '시즌 타율'은 이 경기 이후 시즌 누적입니다.

[작성 항목]
■ 오늘의 타격: 기록으로 본 이 경기 활약과 팀 득점에 대한 기여
■ 눈에 띈 점: 잘한 점과 아쉬운 점 (선구안, 삼진, 장타 등 기록으로 확인되는 것만)
■ 앞으로 볼 점: 다음 경기에서 지켜볼 부분

각 항목 2~3문장, 전체 3문단 안팎으로 쓰십시오.
"""
    else:
        outs = ip_to_outs(player_data.get("ip"))
        prompt = f"""두산 베어스 투수 {player_name}의 이 경기 투구를 분석해 주십시오.

[경기]
{header}

[{player_name} 기록]
{_pitcher_line(player_data)}
(이 경기에서 잡은 아웃카운트: {outs}개)

※ 이닝별 투구 내용, 구종·구속은 기록에 없습니다. '4사구'는 볼넷과 몸에 맞는 공을 합친 수이며, '시즌 ERA'는 이 경기 이후 시즌 누적입니다.

[작성 항목]
■ 오늘의 투구: 맡은 역할(선발/불펜)과 결과, 이닝 소화와 실점
■ 눈에 띈 점: 잘한 점과 아쉬운 점 (삼진, 4사구, 피안타·피홈런 등 기록으로 확인되는 것만)
■ 앞으로 볼 점: 다음 등판에서 지켜볼 부분

각 항목 2~3문장, 전체 3문단 안팎으로 쓰십시오.
"""

    result = _call_claude(prompt, max_tokens=1536)
    save_ai_report(game_id, "player", result, player_name)
    print(f"선수 평가 저장 완료: {player_name} ({game_id})")
    return result


def build_season_prompt(player_name: str, is_pitcher: bool, season_label: str, league_label: str,
                        games: list, season: dict) -> str:
    """시즌 분석 프롬프트. games: 최신순 경기별 기록, season: app.aggregate_by_season_* 결과 한 시즌"""
    recent = games[:10]
    if is_pitcher:
        lines = [f"  {_fmt_date(g['date'])} {DECISION_LABEL.get(g.get('result'), g.get('result')) or '-'} {g.get('ip') or '0'}이닝 피안타 {g['h']} "
                 f"4사구 {g['bb']} 삼진 {g['so']} 자책 {g['er']}" for g in games[:40]]
        r_outs = sum(ip_to_outs(g.get("ip")) for g in recent)
        r_er = sum(g["er"] for g in recent)
        recent_line = (f"최근 {len(recent)}경기: {outs_to_ip(r_outs)}이닝 자책 {r_er} "
                       f"ERA {r_er * 27 / r_outs:.2f}" if r_outs else f"최근 {len(recent)}경기: 이닝 기록 없음")
        totals = (f"{season['games']}경기 {season['wins']}승 {season['loses']}패 {season['holds']}홀드 {season['saves']}세이브, "
                  f"{season['ip']}이닝, ERA {season['era']}, WHIP {season['whip']}, 피안타율 {season['bavg']}, "
                  f"삼진 {season['so']} 4사구 {season['bb']} 피홈런 {season['hr']}")
        items = """■ 시즌 한 줄 평가
■ 시즌 흐름: 경기별 기록으로 본 좋았던 시기와 흔들린 시기, 최근 컨디션
■ 강점: 기록으로 확인되는 무기 (삼진, 이닝 소화, 실점 억제 등)
■ 약점: 기록으로 확인되는 과제 (4사구, 피안타, 피홈런 등)
■ 남은 과제와 기대: 다음 시즌 또는 남은 경기에서 지켜볼 부분"""
        kind = "투수"
    else:
        futures = league_label != "KBO"
        if futures:
            # 퓨처스 타자 기록은 타수·안타·타점·볼넷만 수집됨 (홈런·삼진·2·3루타는 항상 0으로 저장)
            lines = [f"  {_fmt_date(g['date'])} {g['ab']}타수 {g['h']}안타 타점 {g['rbi']} 볼넷 {g['bb']}"
                     for g in games[:40]]
        else:
            lines = [f"  {_fmt_date(g['date'])} {g['ab']}타수 {g['h']}안타 홈런 {g.get('hr', 0)} 타점 {g['rbi']} "
                     f"볼넷 {g['bb']} 삼진 {g.get('so', 0)}" for g in games[:40]]
        r_ab = sum(g["ab"] for g in recent)
        r_h = sum(g["h"] for g in recent)
        recent_line = (f"최근 {len(recent)}경기: {r_ab}타수 {r_h}안타 (타율 {fmt_rate(r_h / r_ab)})"
                       if r_ab else f"최근 {len(recent)}경기: 타수 없음")
        if futures:
            totals = (f"{season['games']}경기 {season['ab']}타수 {season['h']}안타 {season['rbi']}타점 볼넷 {season['bb']}, "
                      f"타율 {season['avg']} 출루율 {season['obp']}")
        else:
            totals = (f"{season['games']}경기 {season['ab']}타수 {season['h']}안타 (2루타 {season['doubles']} 3루타 {season['triples']} "
                      f"홈런 {season['hr']}) {season['rbi']}타점 볼넷 {season['bb']} 삼진 {season['so']}, "
                      f"타율 {season['avg']} 출루율 {season['obp']} 장타율 {season['slg']} OPS {season['ops']}"
                      + (f", wRC+ {season['wrc_plus']}(리그 평균 100 기준 득점 생산력)" if season.get('wrc_plus') not in (None, '-') else ""))
        items = f"""■ 시즌 한 줄 평가
■ 시즌 흐름: 경기별 기록으로 본 좋았던 시기와 부진했던 시기, 최근 컨디션
■ 강점: 기록으로 확인되는 장점 ({"정확성, 출루 등" if futures else "정확성, 출루, 장타 등"})
■ 약점: 기록으로 확인되는 과제 ({"정확성, 출루 등" if futures else "삼진, 출루, 장타 부족 등"})
■ 남은 과제와 기대: 다음 시즌 또는 남은 경기에서 지켜볼 부분"""
        kind = "타자"

    note = ""
    if league_label != "KBO":
        note = "\n※ 퓨처스(2군) 기록입니다. 1군과 수준이 다르다는 점을 감안해 해석하십시오."
        if not is_pitcher:
            note += " 퓨처스 타자 기록은 타수·안타·타점·볼넷만 있으므로 장타력과 삼진은 평가하지 마십시오."

    return f"""두산 베어스 {kind} {player_name}의 {season_label} {league_label} 시즌을 분석해 주십시오.

[시즌 누적]
{totals}
{recent_line}{note}

[경기별 기록] (최신순, 최대 40경기)
{chr(10).join(lines)}

[작성 항목]
{items}

각 항목 2~4문장으로 쓰십시오.
"""


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
