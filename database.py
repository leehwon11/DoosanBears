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
            game_id  TEXT    NOT NULL REFERENCES games(game_id),
            team     TEXT    NOT NULL,   -- "doosan" / "opponent"
            inning   INTEGER NOT NULL,  -- 1 ~ 12
            score    INTEGER NOT NULL DEFAULT 0
        )
    """)

    # ── 3. 타자 기록 ───────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS batter_stats (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id   TEXT    NOT NULL REFERENCES games(game_id),
            name      TEXT    NOT NULL,
            position  TEXT,
            ab        INTEGER DEFAULT 0,   -- 타수
            h         INTEGER DEFAULT 0,   -- 안타
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
            game_id   TEXT    NOT NULL REFERENCES games(game_id),
            name      TEXT    NOT NULL,
            result    TEXT,               -- "승" / "패" / "홀드" / "세이브" / "-"
            ip        TEXT,               -- 이닝 (예: "7.0")
            bf        INTEGER DEFAULT 0,  -- 상대 타자 수
            h         INTEGER DEFAULT 0,  -- 피안타
            hr        INTEGER DEFAULT 0,  -- 피홈런
            bb        INTEGER DEFAULT 0,  -- 볼넷
            so        INTEGER DEFAULT 0,  -- 삼진
            er        INTEGER DEFAULT 0,  -- 자책점
            era       TEXT                -- 평균자책점
        )
    """)

    # ── 5. AI 분석 리포트 ──────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id      TEXT    NOT NULL REFERENCES games(game_id),
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

    # 두산이 홈인지 원정인지 판단
    is_home   = game_info.get("home_team") == "OB"
    doosan_r  = score.get("total", {}).get("home" if is_home else "away", {}).get("R", 0)
    opponent_r = score.get("total", {}).get("away" if is_home else "home", {}).get("R", 0)

    if doosan_r > opponent_r:
        result = "승"
    elif doosan_r < opponent_r:
        result = "패"
    else:
        result = "무"

    # ── games 저장 (중복 무시) ──
    cur.execute("""
        INSERT OR IGNORE INTO games
            (game_id, date, home_team, away_team, home_score, away_score, result, crawled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id,
        data.get("date"),
        score.get("home_team", ""),
        score.get("away_team", ""),
        score.get("total", {}).get("home", {}).get("R", 0),
        score.get("total", {}).get("away", {}).get("R", 0),
        result,
        now,
    ))

    # ── inning_scores 저장 ──
    innings = score.get("innings", {})
    for team_key, team_label in [("home", "doosan" if is_home else "opponent"),
                                  ("away", "opponent" if is_home else "doosan")]:
        for i, s in enumerate(innings.get(team_key, []), start=1):
            cur.execute("""
                INSERT INTO inning_scores (game_id, team, inning, score)
                VALUES (?, ?, ?, ?)
            """, (game_id, team_label, i, s))

    # ── batter_stats 저장 ──
    for b in data.get("batters", []):
        cur.execute("""
            INSERT INTO batter_stats
                (game_id, name, position, ab, h, hr, rbi, r, bb, so, avg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game_id,
            b.get("name"), b.get("position"),
            b.get("ab", 0), b.get("h", 0), b.get("hr", 0),
            b.get("rbi", 0), b.get("r", 0), b.get("bb", 0),
            b.get("so", 0), b.get("avg", ""),
        ))

    # ── pitcher_stats 저장 ──
    for p in data.get("pitchers", []):
        cur.execute("""
            INSERT INTO pitcher_stats
                (game_id, name, result, ip, bf, h, hr, bb, so, er, era)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game_id,
            p.get("name"), p.get("result"), p.get("ip"),
            p.get("bf", 0), p.get("h", 0), p.get("hr", 0),
            p.get("bb", 0), p.get("so", 0), p.get("er", 0),
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
