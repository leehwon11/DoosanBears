"""
두산 베어스 분석 웹사이트 - DB 설계 & 초기화
=============================================
Supabase PostgreSQL 직접 연결 (psycopg2)
"""

import os
import psycopg
from psycopg.rows import dict_row
from datetime import datetime

SUPABASE_HOST = f"db.{os.getenv('SUPABASE_PROJECT_ID', 'grdukdqfciipooradmds')}.supabase.co"
DB_PASSWORD   = os.getenv("DB_PASSWORD", "")

DSN = f"host={SUPABASE_HOST} port=5432 dbname=postgres user=postgres password={DB_PASSWORD} sslmode=require"


def get_connection():
    conn = psycopg.connect(DSN, row_factory=dict_row)
    conn.autocommit = False
    return _PGConn(conn)


class _PGConn:
    """sqlite3 Connection 인터페이스 호환 래퍼"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=None):
        # SQLite 플레이스홀더 ? → PostgreSQL %s 변환
        sql = _to_pg(sql)
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return _PGCursor(cur, self._conn)

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._conn.commit()
        except:
            pass
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()


class _PGCursor:
    """sqlite3 Cursor 인터페이스 호환 래퍼"""

    def __init__(self, cur, conn):
        self._cur = cur
        self._conn = conn

    def fetchall(self):
        try:
            rows = self._cur.fetchall()
            return [_Row(dict(r)) for r in rows]
        except:
            return []

    def fetchone(self):
        try:
            r = self._cur.fetchone()
            return _Row(dict(r)) if r else None
        except:
            return None

    def execute(self, sql: str, params=None):
        sql = _to_pg(sql)
        self._cur.execute(sql, params or ())
        return self

    @property
    def rowcount(self):
        return self._cur.rowcount


class _Row(dict):
    """sqlite3.Row처럼 dict이면서 속성 접근도 가능"""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return None


def _to_pg(sql: str) -> str:
    """SQLite 쿼리를 PostgreSQL 호환으로 변환"""
    # ? → %s
    result = []
    in_string = False
    quote_char = None
    i = 0
    while i < len(sql):
        c = sql[i]
        if in_string:
            result.append(c)
            if c == quote_char:
                in_string = False
        elif c in ("'", '"'):
            in_string = True
            quote_char = c
            result.append(c)
        elif c == '?':
            result.append('%s')
        else:
            result.append(c)
        i += 1
    sql = ''.join(result)

    # SQLite 전용 → PostgreSQL 변환
    sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
    sql = sql.replace('INSERT OR IGNORE INTO', 'INSERT INTO')
    sql = sql.replace('INSERT OR REPLACE INTO', 'INSERT INTO')

    # ON CONFLICT ... DO UPDATE (SQLite와 PostgreSQL 둘 다 지원)
    return sql


def init_db():
    """테이블이 없으면 생성"""
    conn = get_connection()
    cur = conn._conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id          SERIAL PRIMARY KEY,
            game_id     TEXT    UNIQUE NOT NULL,
            date        TEXT    NOT NULL,
            home_team   TEXT    NOT NULL,
            away_team   TEXT    NOT NULL,
            home_score  INTEGER,
            away_score  INTEGER,
            result      TEXT,
            stadium     TEXT,
            crawled_at  TEXT    NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inning_scores (
            id       SERIAL PRIMARY KEY,
            game_id  TEXT    NOT NULL,
            team     TEXT    NOT NULL,
            inning   INTEGER NOT NULL,
            score    INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS batter_stats (
            id            SERIAL PRIMARY KEY,
            game_id       TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            position      TEXT,
            batting_order INTEGER DEFAULT 0,
            ab            INTEGER DEFAULT 0,
            h             INTEGER DEFAULT 0,
            doubles       INTEGER DEFAULT 0,
            triples       INTEGER DEFAULT 0,
            hr            INTEGER DEFAULT 0,
            rbi           INTEGER DEFAULT 0,
            r             INTEGER DEFAULT 0,
            bb            INTEGER DEFAULT 0,
            so            INTEGER DEFAULT 0,
            avg           TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pitcher_stats (
            id          SERIAL PRIMARY KEY,
            game_id     TEXT    NOT NULL,
            name        TEXT    NOT NULL,
            role        TEXT,
            result      TEXT,
            ip          TEXT,
            bf          INTEGER DEFAULT 0,
            pitch_count INTEGER DEFAULT 0,
            ab_against  INTEGER DEFAULT 0,
            h           INTEGER DEFAULT 0,
            hr          INTEGER DEFAULT 0,
            bb          INTEGER DEFAULT 0,
            so          INTEGER DEFAULT 0,
            r           INTEGER DEFAULT 0,
            er          INTEGER DEFAULT 0,
            era         TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS futures_games (
            id         SERIAL PRIMARY KEY,
            game_id    TEXT    UNIQUE NOT NULL,
            date       TEXT    NOT NULL,
            home_team  TEXT,
            away_team  TEXT,
            home_score INTEGER,
            away_score INTEGER,
            result     TEXT,
            stadium    TEXT,
            crawled_at TEXT    NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS futures_batter_stats (
            id            SERIAL PRIMARY KEY,
            game_id       TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            position      TEXT,
            batting_order INTEGER DEFAULT 0,
            ab            INTEGER DEFAULT 0,
            h             INTEGER DEFAULT 0,
            hr            INTEGER DEFAULT 0,
            rbi           INTEGER DEFAULT 0,
            r             INTEGER DEFAULT 0,
            bb            INTEGER DEFAULT 0,
            so            INTEGER DEFAULT 0,
            avg           TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS futures_pitcher_stats (
            id      SERIAL PRIMARY KEY,
            game_id TEXT    NOT NULL,
            name    TEXT    NOT NULL,
            role    TEXT,
            result  TEXT,
            ip      TEXT,
            bf      INTEGER DEFAULT 0,
            h       INTEGER DEFAULT 0,
            hr      INTEGER DEFAULT 0,
            bb      INTEGER DEFAULT 0,
            so      INTEGER DEFAULT 0,
            er      INTEGER DEFAULT 0,
            era     TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_reports (
            id          SERIAL PRIMARY KEY,
            game_id     TEXT    NOT NULL,
            report_type TEXT    NOT NULL,
            player_name TEXT,
            content     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id            SERIAL PRIMARY KEY,
            player_id     TEXT    UNIQUE,
            number        TEXT,
            name          TEXT    NOT NULL,
            position      TEXT,
            batting       TEXT,
            birth         TEXT,
            height_weight TEXT,
            status        TEXT    DEFAULT 'active',
            team_level    TEXT    DEFAULT '1군',
            updated_at    TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players_info_backup (
            id            SERIAL PRIMARY KEY,
            player_id     TEXT,
            number        TEXT,
            name          TEXT,
            position      TEXT,
            batting       TEXT,
            birth         TEXT,
            height_weight TEXT,
            status        TEXT,
            team_level    TEXT,
            updated_at    TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players_daily_change (
            id          SERIAL PRIMARY KEY,
            date        TEXT    NOT NULL,
            change_type TEXT    NOT NULL,
            player_name TEXT    NOT NULL,
            detail      TEXT,
            created_at  TEXT
        )
    """)

    conn._conn.commit()
    conn._conn.close()
    print("DB 초기화 완료 (Supabase PostgreSQL)")


# ──────────────────────────────────────────
# 저장 함수들
# ──────────────────────────────────────────

def save_game(data: dict):
    if not data:
        return

    conn = get_connection()
    cur = conn._conn.cursor()
    now = datetime.now().isoformat()

    game_info = data.get("game_info", {})
    score     = data.get("score_board", {})
    game_id   = game_info.get("game_id")

    if not game_id:
        conn._conn.close()
        return

    home_nm    = game_info.get("home_nm", score.get("home_team", ""))
    away_nm    = game_info.get("away_nm", score.get("away_team", ""))
    home_score = game_info.get("home_score", 0)
    away_score = game_info.get("away_score", 0)

    is_home    = (home_nm == "두산")
    doosan_r   = home_score if is_home else away_score
    opponent_r = away_score if is_home else home_score
    result     = "승" if doosan_r > opponent_r else "패" if doosan_r < opponent_r else "무"
    stadium    = score.get("stadium", "")

    cur.execute("""
        INSERT INTO games
            (game_id, date, home_team, away_team, home_score, away_score, result, stadium, crawled_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(game_id) DO UPDATE SET
            home_score=EXCLUDED.home_score,
            away_score=EXCLUDED.away_score,
            result=EXCLUDED.result,
            stadium=EXCLUDED.stadium,
            crawled_at=EXCLUDED.crawled_at
    """, (game_id, data.get("date"), home_nm, away_nm,
          home_score, away_score, result, stadium, now))

    # inning_scores
    cur.execute("DELETE FROM inning_scores WHERE game_id=%s", (game_id,))
    innings = score.get("innings", {})
    for team_key, team_label in [("home", "doosan" if is_home else "opponent"),
                                  ("away", "opponent" if is_home else "doosan")]:
        for i, s in enumerate(innings.get(team_key, []), start=1):
            cur.execute(
                "INSERT INTO inning_scores (game_id, team, inning, score) VALUES (%s, %s, %s, %s)",
                (game_id, team_label, i, s)
            )

    # batter_stats
    cur.execute("DELETE FROM batter_stats WHERE game_id=%s", (game_id,))
    for b in data.get("batters", []):
        cur.execute("""
            INSERT INTO batter_stats
                (game_id, name, position, batting_order, ab, h, doubles, triples, hr, rbi, r, bb, so, avg)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (game_id, b.get("name"), b.get("position"), b.get("batting_order", 0),
              b.get("ab", 0), b.get("h", 0), b.get("doubles", 0), b.get("triples", 0),
              b.get("hr", 0), b.get("rbi", 0), b.get("r", 0), b.get("bb", 0),
              b.get("so", 0), b.get("avg", "")))

    # pitcher_stats
    cur.execute("DELETE FROM pitcher_stats WHERE game_id=%s", (game_id,))
    for p in data.get("pitchers", []):
        cur.execute("""
            INSERT INTO pitcher_stats
                (game_id, name, role, result, ip, bf, pitch_count, ab_against, h, hr, bb, so, r, er, era)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (game_id, p.get("name"), p.get("role"), p.get("result"), p.get("ip"),
              p.get("bf", 0), p.get("pitch_count", 0), p.get("ab_against", 0),
              p.get("h", 0), p.get("hr", 0), p.get("bb", 0), p.get("so", 0),
              p.get("r", 0), p.get("er", 0), p.get("era", "")))

    conn._conn.commit()
    conn._conn.close()
    print(f"저장 완료: {game_id} ({result})")


def save_futures_game(data: dict):
    if not data:
        return

    conn = get_connection()
    cur = conn._conn.cursor()
    now = datetime.now().isoformat()

    game_info = data.get("game_info", {})
    score     = data.get("score_board", {})
    game_id   = game_info.get("game_id")
    if not game_id:
        conn._conn.close()
        return

    is_home   = game_id[8:10] == "OB"
    home_nm   = game_info.get("home_nm", score.get("home_team", ""))
    away_nm   = game_info.get("away_nm", score.get("away_team", ""))
    hs        = game_info.get("home_score", 0)
    as_       = game_info.get("away_score", 0)
    doosan_r  = hs if is_home else as_
    opp_r     = as_ if is_home else hs
    result    = "승" if doosan_r > opp_r else "패" if doosan_r < opp_r else "무"

    cur.execute("""
        INSERT INTO futures_games
            (game_id, date, home_team, away_team, home_score, away_score, result, crawled_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(game_id) DO NOTHING
    """, (game_id, data.get("date"), home_nm, away_nm, hs, as_, result, now))

    cur.execute("DELETE FROM futures_batter_stats WHERE game_id=%s", (game_id,))
    cur.execute("DELETE FROM futures_pitcher_stats WHERE game_id=%s", (game_id,))

    for b in data.get("batters", []):
        cur.execute("""
            INSERT INTO futures_batter_stats
                (game_id, name, position, batting_order, ab, h, hr, rbi, r, bb, so, avg)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (game_id, b.get("name"), b.get("position"), b.get("batting_order", 0),
              b.get("ab", 0), b.get("h", 0), b.get("hr", 0), b.get("rbi", 0),
              b.get("r", 0), b.get("bb", 0), b.get("so", 0), b.get("avg", "")))

    for p in data.get("pitchers", []):
        cur.execute("""
            INSERT INTO futures_pitcher_stats
                (game_id, name, role, result, ip, bf, h, hr, bb, so, er, era)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (game_id, p.get("name"), p.get("role"), p.get("result"), p.get("ip"),
              p.get("bf", 0), p.get("h", 0), p.get("hr", 0), p.get("bb", 0),
              p.get("so", 0), p.get("er", 0), p.get("era", "")))

    conn._conn.commit()
    conn._conn.close()
    print(f"퓨처스 저장 완료: {game_id} ({result})")


def save_ai_report(game_id: str, report_type: str, content: str, player_name: str = None):
    conn = get_connection()
    conn._conn.cursor().execute("""
        INSERT INTO ai_reports (game_id, report_type, player_name, content, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (game_id, report_type, player_name, content, datetime.now().isoformat()))
    conn._conn.commit()
    conn._conn.close()


# ──────────────────────────────────────────
# 조회 함수들
# ──────────────────────────────────────────

def get_recent_games(limit: int = 10) -> list:
    conn = get_connection()
    cur = conn._conn.cursor()
    cur.execute("SELECT * FROM games ORDER BY date DESC LIMIT %s", (limit,))
    rows = [_Row(dict(r)) for r in cur.fetchall()]
    conn._conn.close()
    return rows


def get_recent_futures_games(limit: int = 10) -> list:
    try:
        conn = get_connection()
        cur = conn._conn.cursor()
        cur.execute("SELECT * FROM futures_games ORDER BY date DESC LIMIT %s", (limit,))
        rows = [_Row(dict(r)) for r in cur.fetchall()]
        conn._conn.close()
        return rows
    except:
        return []


def get_game_detail(game_id: str) -> dict:
    conn = get_connection()
    cur = conn._conn.cursor()

    cur.execute("SELECT * FROM games WHERE game_id = %s", (game_id,))
    game = cur.fetchone()

    cur.execute("SELECT * FROM inning_scores WHERE game_id = %s ORDER BY team, inning", (game_id,))
    innings = [_Row(dict(r)) for r in cur.fetchall()]

    cur.execute("SELECT * FROM batter_stats WHERE game_id = %s", (game_id,))
    batters = [_Row(dict(r)) for r in cur.fetchall()]

    cur.execute("SELECT * FROM pitcher_stats WHERE game_id = %s", (game_id,))
    pitchers = [_Row(dict(r)) for r in cur.fetchall()]

    cur.execute("SELECT * FROM ai_reports WHERE game_id = %s", (game_id,))
    reports = [_Row(dict(r)) for r in cur.fetchall()]

    conn._conn.close()
    return {
        "game":     _Row(dict(game)) if game else {},
        "innings":  innings,
        "batters":  batters,
        "pitchers": pitchers,
        "reports":  reports,
    }


def get_player_stats(name: str) -> list:
    conn = get_connection()
    cur = conn._conn.cursor()
    cur.execute("""
        SELECT b.*, g.date, g.result
        FROM batter_stats b
        JOIN games g ON b.game_id = g.game_id
        WHERE b.name = %s
        ORDER BY g.date DESC
    """, (name,))
    rows = [_Row(dict(r)) for r in cur.fetchall()]
    conn._conn.close()
    return rows


class _Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return None


if __name__ == "__main__":
    init_db()