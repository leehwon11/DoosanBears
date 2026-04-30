"""
두산 베어스 분석 웹사이트 - DB 설계 & 초기화
=============================================
SQLite 사용 (파일 하나로 관리, Railway 배포에 적합)

테이블 구조:
  1. games         - 경기 기본 정보 & 스코어
  2. inning_scores - 이닝별 점수
  3. batter_stats  - 타자 기록
  4. pitcher_stats - 투수 기록
  5. ai_reports    - Claude AI 분석 리포트

실행:
  python database.py
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "doosan.db")


def get_connection():
    """DB 연결 반환. 어디서든 이 함수로 연결해요."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 딕셔너리처럼 접근 가능
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """테이블이 없으면 생성합니다. 서버 시작할 때 한 번 호출해요."""
    conn = get_connection()
    cur = conn.cursor()

    # ── 1. 경기 기본 정보 ──────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     TEXT    UNIQUE NOT NULL,  -- KBO gmkey (예: 20260424OBHH02)
            date        TEXT    NOT NULL,          -- "20260424"
            home_team   TEXT    NOT NULL,
            away_team   TEXT    NOT NULL,
            home_score  INTEGER,
            away_score  INTEGER,
            result      TEXT,                      -- "승" / "패" / "무"
            stadium     TEXT,
            crawled_at  TEXT    NOT NULL           -- 크롤링 시각
        )
    """)

    # ── 2. 이닝별 점수 ─────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inning_scores (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id  TEXT    NOT NULL,
            team     TEXT    NOT NULL,   -- "doosan" / "opponent"
            inning   INTEGER NOT NULL,  -- 1 ~ 12
            score    INTEGER NOT NULL DEFAULT 0
        )
    """)

    # ── 3. 타자 기록 ───────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS batter_stats (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id   TEXT    NOT NULL,
            name      TEXT    NOT NULL,
            position  TEXT,
            batting_order INTEGER DEFAULT 0,  -- 타순
            ab        INTEGER DEFAULT 0,   -- 타수
            h         INTEGER DEFAULT 0,   -- 안타
            doubles   INTEGER DEFAULT 0,   -- 2루타
            triples   INTEGER DEFAULT 0,   -- 3루타
            hr        INTEGER DEFAULT 0,   -- 홈런
            rbi       INTEGER DEFAULT 0,   -- 타점
            r         INTEGER DEFAULT 0,   -- 득점
            bb        INTEGER DEFAULT 0,   -- 볼넷
            so        INTEGER DEFAULT 0,   -- 삼진
            avg       TEXT                 -- 타율 (예: ".287")
        )
    """)

    # ── 4. 투수 기록 ───────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pitcher_stats (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id   TEXT    NOT NULL,
            name      TEXT    NOT NULL,
            role      TEXT,               -- "선발" / "불펜" / "마무리"
            result    TEXT,               -- "승" / "패" / "홀드" / "세이브" / "-"
            ip          TEXT,               -- 이닝 (예: "7.0")
            bf          INTEGER DEFAULT 0,  -- 상대 타자 수
            pitch_count INTEGER DEFAULT 0,  -- 투구수
            ab_against  INTEGER DEFAULT 0,  -- 상대 타수
            h           INTEGER DEFAULT 0,  -- 피안타
            hr          INTEGER DEFAULT 0,  -- 피홈런
            bb          INTEGER DEFAULT 0,  -- 4사구
            so          INTEGER DEFAULT 0,  -- 삼진
            r           INTEGER DEFAULT 0,  -- 실점
            er          INTEGER DEFAULT 0,  -- 자책점
            era         TEXT                -- 평균자책점
        )
    """)

    # ── 5. 퓨처스 경기 ────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS futures_games (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     TEXT    UNIQUE NOT NULL,
            date        TEXT    NOT NULL,
            home_team   TEXT,
            away_team   TEXT,
            home_score  INTEGER,
            away_score  INTEGER,
            result      TEXT,
            stadium     TEXT,
            crawled_at  TEXT    NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS futures_batter_stats (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id   TEXT    NOT NULL REFERENCES futures_games(game_id),
            name      TEXT    NOT NULL,
            position  TEXT,
            batting_order INTEGER DEFAULT 0,
            ab        INTEGER DEFAULT 0,
            h         INTEGER DEFAULT 0,
            hr        INTEGER DEFAULT 0,
            rbi       INTEGER DEFAULT 0,
            r         INTEGER DEFAULT 0,
            bb        INTEGER DEFAULT 0,
            so        INTEGER DEFAULT 0,
            avg       TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS futures_pitcher_stats (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id   TEXT    NOT NULL REFERENCES futures_games(game_id),
            name      TEXT    NOT NULL,
            role      TEXT,
            result    TEXT,
            ip        TEXT,
            bf        INTEGER DEFAULT 0,
            h         INTEGER DEFAULT 0,
            hr        INTEGER DEFAULT 0,
            bb        INTEGER DEFAULT 0,
            so        INTEGER DEFAULT 0,
            er        INTEGER DEFAULT 0,
            era       TEXT
        )
    """)

    # ── 6. AI 분석 리포트 ──────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id      TEXT    NOT NULL,
            report_type  TEXT    NOT NULL,  -- "game" (경기 종합) / "player" (선수 개인)
            player_name  TEXT,              -- report_type이 "player"일 때만 사용
            content      TEXT    NOT NULL,  -- Claude가 생성한 분석 텍스트
            created_at   TEXT    NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print(f"DB 초기화 완료: {DB_PATH}")


# ──────────────────────────────────────────
# 저장 함수들 (kbo_crawler.py 결과를 받아서 저장)
# ──────────────────────────────────────────

def save_game(data: dict):
    """
    crawl_today_game() 결과를 DB에 저장합니다.
    이미 저장된 game_id면 덮어쓰지 않고 스킵해요.
    """
    if not data:
        return

    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat()

    game_info = data.get("game_info", {})
    score     = data.get("score_board", {})
    game_id   = game_info.get("game_id")

    if not game_id:
        print("game_id 없음 — 저장 스킵")
        conn.close()
        return

    # game_info에서 직접 점수/팀명 가져오기 (크롤러 최종버전 기준)
    home_nm    = game_info.get("home_nm", score.get("home_team", ""))
    away_nm    = game_info.get("away_nm", score.get("away_team", ""))
    home_score = game_info.get("home_score", score.get("total", {}).get("home", {}).get("R", 0))
    away_score = game_info.get("away_score", score.get("total", {}).get("away", {}).get("R", 0))

    # 두산이 홈인지 원정인지 판단 (home_nm 기준)
    is_home = (home_nm == "두산")
    doosan_r   = home_score if is_home else away_score
    opponent_r = away_score if is_home else home_score

    if doosan_r > opponent_r:
        result = "승"
    elif doosan_r < opponent_r:
        result = "패"
    else:
        result = "무"

    # ── games 저장 (있으면 업데이트) ──
    stadium = score.get("stadium", "")

    cur.execute("""
        INSERT INTO games
            (game_id, date, home_team, away_team, home_score, away_score, result, stadium, crawled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET
            home_score=excluded.home_score,
            away_score=excluded.away_score,
            result=excluded.result,
            stadium=excluded.stadium,
            crawled_at=excluded.crawled_at
    """, (
        game_id,
        data.get("date"),
        home_nm,
        away_nm,
        home_score,
        away_score,
        result,
        stadium,
        now,
    ))

    # ── inning_scores 저장 ──
    innings = score.get("innings", {})
    # 기존 이닝 데이터 삭제 후 재저장 (중복 방지)
    cur.execute("DELETE FROM inning_scores WHERE game_id=?", (game_id,))
    for team_key, team_label in [("home", "doosan" if is_home else "opponent"),
                                  ("away", "opponent" if is_home else "doosan")]:
        for i, s in enumerate(innings.get(team_key, []), start=1):
            cur.execute("""
                INSERT INTO inning_scores (game_id, team, inning, score)
                VALUES (?, ?, ?, ?)
            """, (game_id, team_label, i, s))

    # ── batter_stats 저장 ──
    # 기존 타자/투수 기록 삭제 후 재저장 (중복 방지)
    cur.execute("DELETE FROM batter_stats WHERE game_id=?", (game_id,))
    cur.execute("DELETE FROM pitcher_stats WHERE game_id=?", (game_id,))

    for b in data.get("batters", []):
        cur.execute("""
            INSERT INTO batter_stats
                (game_id, name, position, batting_order, ab, h, doubles, triples, hr, rbi, r, bb, so, avg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game_id,
            b.get("name"), b.get("position"),
            b.get("batting_order", 0),
            b.get("ab", 0), b.get("h", 0),
            b.get("doubles", 0), b.get("triples", 0),
            b.get("hr", 0),
            b.get("rbi", 0), b.get("r", 0), b.get("bb", 0),
            b.get("so", 0), b.get("avg", ""),
        ))

    # ── pitcher_stats 저장 ──
    for p in data.get("pitchers", []):
        cur.execute("""
            INSERT INTO pitcher_stats
                (game_id, name, role, result, ip, bf, pitch_count, ab_against, h, hr, bb, so, r, er, era)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game_id,
            p.get("name"), p.get("role"), p.get("result"), p.get("ip"),
            p.get("bf", 0), p.get("pitch_count", 0), p.get("ab_against", 0),
            p.get("h", 0), p.get("hr", 0),
            p.get("bb", 0), p.get("so", 0), p.get("r", 0), p.get("er", 0),
            p.get("era", ""),
        ))

    conn.commit()
    conn.close()
    print(f"저장 완료: {game_id} ({result})")


def save_ai_report(game_id: str, report_type: str, content: str, player_name: str = None):
    """AI 분석 리포트를 저장합니다."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO ai_reports (game_id, report_type, player_name, content, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (game_id, report_type, player_name, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────
# 조회 함수들 (Flask에서 사용)
# ──────────────────────────────────────────

def get_recent_games(limit: int = 10) -> list:
    """최근 경기 목록 반환 (메인 페이지용)"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM games
        ORDER BY date DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_game_detail(game_id: str) -> dict:
    """경기 상세 정보 반환 (경기 리포트 페이지용)"""
    conn = get_connection()

    game     = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
    innings  = conn.execute("SELECT * FROM inning_scores WHERE game_id = ? ORDER BY team, inning", (game_id,)).fetchall()
    batters  = conn.execute("SELECT * FROM batter_stats WHERE game_id = ?", (game_id,)).fetchall()
    pitchers = conn.execute("SELECT * FROM pitcher_stats WHERE game_id = ?", (game_id,)).fetchall()
    reports  = conn.execute("SELECT * FROM ai_reports WHERE game_id = ?", (game_id,)).fetchall()

    conn.close()
    return {
        "game":     dict(game) if game else {},
        "innings":  [dict(r) for r in innings],
        "batters":  [dict(r) for r in batters],
        "pitchers": [dict(r) for r in pitchers],
        "reports":  [dict(r) for r in reports],
    }


def get_player_stats(name: str) -> list:
    """선수 시즌 전체 기록 반환 (선수 페이지용)"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT b.*, g.date, g.result
        FROM batter_stats b
        JOIN games g ON b.game_id = g.game_id
        WHERE b.name = ?
        ORDER BY g.date DESC
    """, (name,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────
# 실행
# ──────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    # 테이블 목록 확인
    conn = get_connection()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print("생성된 테이블:", [t["name"] for t in tables])
    conn.close()


def save_futures_game(data: dict):
    """퓨처스 경기 데이터를 DB에 저장합니다."""
    if not data:
        return

    conn = get_connection()
    cur  = conn.cursor()
    now  = datetime.now().isoformat()

    game_info = data.get("game_info", {})
    score     = data.get("score_board", {})
    game_id   = game_info.get("game_id")
    if not game_id:
        conn.close()
        return

    is_home   = game_id[8:10] == "OB"
    doosan_r  = game_info.get("home_score" if is_home else "away_score", 0)
    opponent_r = game_info.get("away_score" if is_home else "home_score", 0)
    result = "승" if doosan_r > opponent_r else "패" if doosan_r < opponent_r else "무"

    home_nm = game_info.get("home_nm", score.get("home_team",""))
    away_nm = game_info.get("away_nm", score.get("away_team",""))

    cur.execute("""
        INSERT OR IGNORE INTO futures_games
            (game_id, date, home_team, away_team, home_score, away_score, result, crawled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (game_id, data.get("date"), home_nm, away_nm,
          game_info.get("home_score",0), game_info.get("away_score",0), result, now))

    # 기존 퓨처스 기록 삭제 후 재저장
    cur.execute("DELETE FROM futures_batter_stats WHERE game_id=?", (game_id,))
    cur.execute("DELETE FROM futures_pitcher_stats WHERE game_id=?", (game_id,))

    for b in data.get("batters", []):
        cur.execute("""
            INSERT INTO futures_batter_stats
                (game_id, name, position, batting_order, ab, h, hr, rbi, r, bb, so, avg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_id, b.get("name"), b.get("position"), b.get("batting_order",0),
              b.get("ab",0), b.get("h",0), b.get("hr",0), b.get("rbi",0),
              b.get("r",0), b.get("bb",0), b.get("so",0), b.get("avg","")))

    for p in data.get("pitchers", []):
        cur.execute("""
            INSERT INTO futures_pitcher_stats
                (game_id, name, role, result, ip, bf, h, hr, bb, so, er, era)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_id, p.get("name"), p.get("role"), p.get("result"), p.get("ip"),
              p.get("bf",0), p.get("h",0), p.get("hr",0), p.get("bb",0),
              p.get("so",0), p.get("er",0), p.get("era","")))

    conn.commit()
    conn.close()
    print(f"퓨처스 저장 완료: {game_id} ({result})")


def get_recent_futures_games(limit: int = 10) -> list:
    """최근 퓨처스 경기 목록"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM futures_games ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    except:
        rows = []
    conn.close()
    return [dict(r) for r in rows]
