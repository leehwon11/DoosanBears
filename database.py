"""
두산 베어스 분석 웹사이트 - DB 설계 & 초기화
=============================================
Supabase REST API 사용 (PostgreSQL 기반)
"""

import os
import requests
from datetime import datetime

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _get(table: str, params: dict = None) -> list:
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, params=params)
    if resp.status_code == 200:
        return resp.json()
    return []


def _post(table: str, data) -> dict:
    h = {**HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    resp = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, json=data)
    return resp.json() if resp.ok else {}


def _delete(table: str, params: dict):
    requests.delete(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, params=params)


def _patch(table: str, params: dict, data: dict):
    h = {**HEADERS, "Prefer": "return=representation"}
    resp = requests.patch(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params=params, json=data)
    return resp.json() if resp.ok else {}


# ── Row 호환 클래스 ──
class Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return None


def _rows(data: list) -> list:
    return [Row(r) for r in data]


def get_connection():
    """Supabase에서는 연결 객체 불필요 — 호환용 더미 반환"""
    return _SupabaseConn()


class _SupabaseConn:
    """SQLite conn 인터페이스를 흉내낸 Supabase 래퍼"""

    def execute(self, sql: str, params=None):
        return _FakeResult([])

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def init_db():
    """Supabase에서는 테이블을 SQL Editor에서 직접 생성합니다."""
    print("Supabase 모드: 테이블은 Supabase SQL Editor에서 생성 필요")
    print(f"SUPABASE_URL: {SUPABASE_URL}")
    print(f"SUPABASE_KEY 설정됨: {'예' if SUPABASE_KEY else '아니오'}")


# ──────────────────────────────────────────
# 저장 함수들
# ──────────────────────────────────────────

def save_game(data: dict):
    if not data:
        return

    now = datetime.now().isoformat()
    game_info = data.get("game_info", {})
    score     = data.get("score_board", {})
    game_id   = game_info.get("game_id")

    if not game_id:
        print("game_id 없음 — 저장 스킵")
        return

    home_nm    = game_info.get("home_nm", score.get("home_team", ""))
    away_nm    = game_info.get("away_nm", score.get("away_team", ""))
    home_score = game_info.get("home_score", 0)
    away_score = game_info.get("away_score", 0)

    is_home = (home_nm == "두산")
    doosan_r   = home_score if is_home else away_score
    opponent_r = away_score if is_home else home_score

    if doosan_r > opponent_r:
        result = "승"
    elif doosan_r < opponent_r:
        result = "패"
    else:
        result = "무"

    stadium = score.get("stadium", "")

    # games upsert
    _post("games", {
        "game_id": game_id,
        "date": data.get("date"),
        "home_team": home_nm,
        "away_team": away_nm,
        "home_score": home_score,
        "away_score": away_score,
        "result": result,
        "stadium": stadium,
        "crawled_at": now,
    })

    # inning_scores - 기존 삭제 후 재저장
    _delete("inning_scores", {"game_id": f"eq.{game_id}"})
    innings = score.get("innings", {})
    inning_rows = []
    for team_key, team_label in [("home", "doosan" if is_home else "opponent"),
                                  ("away", "opponent" if is_home else "doosan")]:
        for i, s in enumerate(innings.get(team_key, []), start=1):
            inning_rows.append({"game_id": game_id, "team": team_label, "inning": i, "score": s})
    if inning_rows:
        _post("inning_scores", inning_rows)

    # batter_stats
    _delete("batter_stats", {"game_id": f"eq.{game_id}"})
    batter_rows = []
    for b in data.get("batters", []):
        batter_rows.append({
            "game_id": game_id,
            "name": b.get("name"),
            "position": b.get("position"),
            "batting_order": b.get("batting_order", 0),
            "ab": b.get("ab", 0),
            "h": b.get("h", 0),
            "doubles": b.get("doubles", 0),
            "triples": b.get("triples", 0),
            "hr": b.get("hr", 0),
            "rbi": b.get("rbi", 0),
            "r": b.get("r", 0),
            "bb": b.get("bb", 0),
            "so": b.get("so", 0),
            "avg": b.get("avg", ""),
        })
    if batter_rows:
        _post("batter_stats", batter_rows)

    # pitcher_stats
    _delete("pitcher_stats", {"game_id": f"eq.{game_id}"})
    pitcher_rows = []
    for p in data.get("pitchers", []):
        pitcher_rows.append({
            "game_id": game_id,
            "name": p.get("name"),
            "role": p.get("role"),
            "result": p.get("result"),
            "ip": p.get("ip"),
            "bf": p.get("bf", 0),
            "pitch_count": p.get("pitch_count", 0),
            "ab_against": p.get("ab_against", 0),
            "h": p.get("h", 0),
            "hr": p.get("hr", 0),
            "bb": p.get("bb", 0),
            "so": p.get("so", 0),
            "r": p.get("r", 0),
            "er": p.get("er", 0),
            "era": p.get("era", ""),
        })
    if pitcher_rows:
        _post("pitcher_stats", pitcher_rows)

    print(f"저장 완료: {game_id} ({result})")


def save_futures_game(data: dict):
    if not data:
        return

    now = datetime.now().isoformat()
    game_info = data.get("game_info", {})
    score     = data.get("score_board", {})
    game_id   = game_info.get("game_id")
    if not game_id:
        return

    is_home   = game_id[8:10] == "OB"
    home_nm   = game_info.get("home_nm", score.get("home_team", ""))
    away_nm   = game_info.get("away_nm", score.get("away_team", ""))
    hs        = game_info.get("home_score", 0)
    as_       = game_info.get("away_score", 0)
    doosan_r  = hs if is_home else as_
    opp_r     = as_ if is_home else hs
    result    = "승" if doosan_r > opp_r else "패" if doosan_r < opp_r else "무"

    _post("futures_games", {
        "game_id": game_id,
        "date": data.get("date"),
        "home_team": home_nm,
        "away_team": away_nm,
        "home_score": hs,
        "away_score": as_,
        "result": result,
        "crawled_at": now,
    })

    _delete("futures_batter_stats", {"game_id": f"eq.{game_id}"})
    _delete("futures_pitcher_stats", {"game_id": f"eq.{game_id}"})

    batter_rows = []
    for b in data.get("batters", []):
        batter_rows.append({
            "game_id": game_id,
            "name": b.get("name"), "position": b.get("position"),
            "batting_order": b.get("batting_order", 0),
            "ab": b.get("ab", 0), "h": b.get("h", 0), "hr": b.get("hr", 0),
            "rbi": b.get("rbi", 0), "r": b.get("r", 0),
            "bb": b.get("bb", 0), "so": b.get("so", 0), "avg": b.get("avg", ""),
        })
    if batter_rows:
        _post("futures_batter_stats", batter_rows)

    pitcher_rows = []
    for p in data.get("pitchers", []):
        pitcher_rows.append({
            "game_id": game_id,
            "name": p.get("name"), "role": p.get("role"), "result": p.get("result"),
            "ip": p.get("ip"), "bf": p.get("bf", 0),
            "h": p.get("h", 0), "hr": p.get("hr", 0),
            "bb": p.get("bb", 0), "so": p.get("so", 0),
            "er": p.get("er", 0), "era": p.get("era", ""),
        })
    if pitcher_rows:
        _post("futures_pitcher_stats", pitcher_rows)

    print(f"퓨처스 저장 완료: {game_id} ({result})")


def save_ai_report(game_id: str, report_type: str, content: str, player_name: str = None):
    _post("ai_reports", {
        "game_id": game_id,
        "report_type": report_type,
        "player_name": player_name,
        "content": content,
        "created_at": datetime.now().isoformat(),
    })


# ──────────────────────────────────────────
# 조회 함수들
# ──────────────────────────────────────────

def get_recent_games(limit: int = 10) -> list:
    rows = _get("games", {"order": "date.desc", "limit": limit})
    return [Row(r) for r in rows]


def get_recent_futures_games(limit: int = 10) -> list:
    try:
        rows = _get("futures_games", {"order": "date.desc", "limit": limit})
        return [Row(r) for r in rows]
    except:
        return []


def get_game_detail(game_id: str) -> dict:
    game     = _get("games",         {"game_id": f"eq.{game_id}"})
    innings  = _get("inning_scores", {"game_id": f"eq.{game_id}", "order": "team.asc,inning.asc"})
    batters  = _get("batter_stats",  {"game_id": f"eq.{game_id}"})
    pitchers = _get("pitcher_stats", {"game_id": f"eq.{game_id}"})
    reports  = _get("ai_reports",    {"game_id": f"eq.{game_id}"})

    return {
        "game":     Row(game[0]) if game else {},
        "innings":  _rows(innings),
        "batters":  _rows(batters),
        "pitchers": _rows(pitchers),
        "reports":  _rows(reports),
    }


def get_player_stats(name: str) -> list:
    # batter_stats에서 name으로 필터, games join은 REST API에서 복잡하므로 별도 조회
    rows = _get("batter_stats", {"name": f"eq.{name}", "order": "game_id.desc"})
    result = []
    for r in rows:
        game = _get("games", {"game_id": f"eq.{r['game_id']}"})
        if game:
            r["date"] = game[0].get("date", "")
            r["result"] = game[0].get("result", "")
        result.append(Row(r))
    return result


if __name__ == "__main__":
    init_db()
