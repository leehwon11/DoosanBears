"""
두산 베어스 분석 웹사이트 - Flask 웹서버
"""

import os
import time
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, abort, request
from dotenv import load_dotenv
from database import init_db, get_recent_games, get_game_detail, get_connection, get_recent_futures_games

load_dotenv()
init_db()


# KBO 리그 연도별 wOBA 상수 (매년 업데이트)
KBO_WOBA_CONSTANTS = {
    2023: {"woba_avg": 0.320, "woba_scale": 1.21, "r_pa": 0.123, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
    2024: {"woba_avg": 0.325, "woba_scale": 1.22, "r_pa": 0.127, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
    2025: {"woba_avg": 0.323, "woba_scale": 1.21, "r_pa": 0.125, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
    2026: {"woba_avg": 0.323, "woba_scale": 1.21, "r_pa": 0.125, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
}

SAVE_CODES = ("세이브", "세", "S")
HOLD_CODES = ("홀드", "H")


def calc_woba(ab, h, doubles, triples, hr, bb, year=None):
    """wOBA 계산"""
    yr = year or datetime.now().year
    c = KBO_WOBA_CONSTANTS.get(yr, KBO_WOBA_CONSTANTS[2025])
    singles = h - doubles - triples - hr
    denom = ab + bb
    if denom == 0:
        return 0.0
    return (c["w_bb"]*bb + c["w_1b"]*singles + c["w_2b"]*doubles + c["w_3b"]*triples + c["w_hr"]*hr) / denom


def calc_wrc_plus(woba, year=None):
    """wRC+ 계산 (100=리그평균, 150=평균보다 50% 좋음)"""
    yr = year or datetime.now().year
    c = KBO_WOBA_CONSTANTS.get(yr, KBO_WOBA_CONSTANTS[2025])
    if c["r_pa"] == 0:
        return 100
    wrc_plus = ((woba - c["woba_avg"]) / c["woba_scale"] + c["r_pa"]) / c["r_pa"] * 100
    return round(wrc_plus)


def ip_to_outs(ip) -> int:
    """이닝 문자열('5 2/3', '1/3', '7') → 아웃카운트"""
    outs = 0
    try:
        for part in str(ip or "0").split():
            if "/" in part:
                n, d = part.split("/")
                outs += int(n) * 3 // int(d)
            else:
                outs += int(part) * 3
    except ValueError:
        return 0
    return outs


def fmt_rate(v: float) -> str:
    """비율 기록 표기 (0.262 → .262, 1.023은 그대로)"""
    t = f"{v:.3f}"
    return t[1:] if t.startswith("0.") else t


def outs_to_ip(outs: int) -> str:
    """아웃카운트 → '45.2' 형식 이닝 표기"""
    return f"{outs // 3}.{outs % 3}" if outs > 0 else "0"


def simplify_pos(pos):
    """세부 포지션 → 투수/포수/내야수/외야수"""
    if not pos: return '기타'
    if pos in ('투수',): return '투수'
    if pos in ('포수',): return '포수'
    if pos in ('1루수', '2루수', '3루수', '유격수', '내야수'): return '내야수'
    if pos in ('좌익수', '우익수', '중견수', '외야수'): return '외야수'
    return '내야수'  # 지명타자 등은 내야수로


def _query(conn, sql, params=(), one=False, default=None):
    """쿼리 실패 시 롤백 후 기본값 반환.
    PostgreSQL은 한 쿼리가 실패하면 트랜잭션이 abort되어 이후 쿼리도 전부 실패하므로 꼭 롤백해야 함."""
    try:
        cur = conn.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()
    except Exception as e:
        print(f"쿼리 실패: {e}")
        conn.rollback()
        return default if default is not None else (None if one else [])


def _latest_season(conn, table="games") -> str:
    """기록이 있는 가장 최근 시즌 (올해 기록이 없으면 작년 등)"""
    row = _query(conn, f"SELECT MAX(substr(date,1,4)) yr FROM {table}", one=True)
    return (row and row["yr"]) or str(datetime.now().year)


def _team_season_stats(conn, year: str) -> dict:
    """팀 시즌 집계 (승패, 타율, 홈런, ERA 등)"""
    like = year + '%'
    bat = _query(conn, """
        SELECT SUM(ab) ab, SUM(h) h, SUM(hr) hr, SUM(rbi) rbi, SUM(bb) bb, SUM(so) so
        FROM batter_stats b JOIN games g ON b.game_id = g.game_id
        WHERE g.date LIKE ?
    """, (like,), one=True) or {}
    pit_rows = _query(conn, """
        SELECT p.ip, p.er, p.so FROM pitcher_stats p JOIN games g ON p.game_id = g.game_id
        WHERE g.date LIKE ?
    """, (like,))
    wl = _query(conn, """
        SELECT result, COUNT(*) cnt FROM games
        WHERE date LIKE ? AND result IN ('승','패','무')
        GROUP BY result
    """, (like,))

    wl_dict = {r['result']: r['cnt'] for r in wl}
    wins, loses, draws = wl_dict.get('승', 0), wl_dict.get('패', 0), wl_dict.get('무', 0)
    ab, h = bat.get('ab') or 0, bat.get('h') or 0
    outs = sum(ip_to_outs(p['ip']) for p in pit_rows)
    er = sum(p['er'] or 0 for p in pit_rows)

    return {
        "year": year,
        "wins": wins, "loses": loses, "draws": draws,
        "win_pct": fmt_rate(wins/(wins+loses)) if (wins + loses) else ".000",
        "avg": fmt_rate(h/ab) if ab else ".000",
        "hr": bat.get('hr') or 0,
        "rbi": bat.get('rbi') or 0,
        "bb": bat.get('bb') or 0,
        "so_bat": bat.get('so') or 0,
        "era": f"{er*27/outs:.2f}" if outs else "-",
        "so_pit": sum(p['so'] or 0 for p in pit_rows),
    }


# 다음 경기 정보는 외부(KBO) 요청이라 느림 → 30분 캐시
_next_game_cache = {"ts": 0.0, "data": None}
_NEXT_GAME_TTL = 30 * 60


def cached_next_game():
    now = time.time()
    if now - _next_game_cache["ts"] < _NEXT_GAME_TTL:
        return _next_game_cache["data"]
    try:
        from kbo_crawler import get_next_game
        data = get_next_game()
    except Exception as e:
        print(f"다음 경기 조회 실패: {e}")
        data = None
    _next_game_cache.update(ts=now, data=data)
    return data


app = Flask(__name__)


@app.template_filter("rate")
def rate_filter(v):
    """'0.285' 같은 크롤링 문자열도 '.285'로 표기"""
    try:
        return fmt_rate(float(v))
    except (TypeError, ValueError):
        return v or "-"


# ──────────────────────────────────────────
# 페이지 라우터
# ──────────────────────────────────────────

@app.route("/")
def index():
    games = get_recent_games(limit=5)
    futures_games = get_recent_futures_games(limit=5)
    next_game = cached_next_game()

    conn = get_connection()
    year = _latest_season(conn)
    team_stats = _team_season_stats(conn, year)
    # 최근 10경기 흐름 (오래된 → 최신)
    form = _query(conn, """
        SELECT result FROM games WHERE result IN ('승','패','무')
        ORDER BY date DESC, game_id DESC LIMIT 10
    """)
    conn.close()

    return render_template("index.html",
        games=games, futures_games=futures_games,
        team_stats=team_stats, next_game=next_game,
        recent_form=[r['result'] for r in reversed(form)],
    )


@app.route("/compare")
def compare_page():
    """선수 비교 페이지"""
    conn = get_connection()
    years = [r['yr'] for r in _query(conn,
        "SELECT DISTINCT substr(date,1,4) yr FROM games ORDER BY yr DESC")]
    target_year = request.args.get('year') or (years[0] if years else str(datetime.now().year))

    batters_raw = _query(conn,
        """SELECT DISTINCT b.name, b.position
           FROM batter_stats b JOIN games g ON b.game_id=g.game_id
           WHERE substr(g.date,1,4)=? ORDER BY b.name""", (target_year,))
    pitchers_raw = _query(conn,
        """SELECT DISTINCT p.name, '투수' as position
           FROM pitcher_stats p JOIN games g ON p.game_id=g.game_id
           WHERE substr(g.date,1,4)=? ORDER BY p.name""", (target_year,))
    conn.close()

    # 투수 우선 (투수가 대타로 나온 기록 때문에 타자로 분류되는 것 방지)
    seen = set()
    players = []
    for p in list(pitchers_raw) + list(batters_raw):
        if p['name'] not in seen:
            seen.add(p['name'])
            players.append({'name': p['name'], 'position': simplify_pos(p['position'])})
    players.sort(key=lambda x: (x['position'], x['name']))

    return render_template("compare.html",
        players=players,
        years=years or [target_year],
        current_year=target_year,
    )


@app.route("/api/compare")
def api_compare():
    """두 선수 스탯 비교 JSON"""
    p1 = request.args.get("p1", "")
    p2 = request.args.get("p2", "")
    year = request.args.get("year") or str(datetime.now().year)
    if not p1 or not p2:
        return jsonify({"error": "선수명 필요"}), 400

    conn = get_connection()
    like = year + '%'

    def get_batter(name):
        row = _query(conn, """
            SELECT SUM(ab) ab, SUM(h) h, SUM(doubles) doubles, SUM(triples) triples,
                   SUM(hr) hr, SUM(rbi) rbi, SUM(r) r, SUM(bb) bb, SUM(so) so, COUNT(*) games
            FROM batter_stats b JOIN games g ON b.game_id = g.game_id
            WHERE b.name=? AND g.date LIKE ?
        """, (name, like), one=True)
        s = {k: (v or 0) for k, v in dict(row or {}).items()}
        ab, h, bb = s.get('ab', 0), s.get('h', 0), s.get('bb', 0)
        if ab:
            singles = h - s['doubles'] - s['triples'] - s['hr']
            tb = singles + 2*s['doubles'] + 3*s['triples'] + 4*s['hr']
            obp = (h + bb) / (ab + bb)
            s.update(avg=fmt_rate(h/ab), obp=fmt_rate(obp), slg=fmt_rate(tb/ab), ops=fmt_rate(obp + tb/ab))
        return s

    def get_pitcher(name):
        rows = _query(conn, """
            SELECT p.ip, p.er, p.so, p.h, p.bb, p.result
            FROM pitcher_stats p JOIN games g ON p.game_id = g.game_id
            WHERE p.name=? AND g.date LIKE ?
        """, (name, like))
        outs = sum(ip_to_outs(r['ip']) for r in rows)
        s = {
            "games": len(rows),
            "wins":  sum(1 for r in rows if r['result'] == '승'),
            "loses": sum(1 for r in rows if r['result'] == '패'),
            "holds": sum(1 for r in rows if r['result'] in HOLD_CODES),
            "saves": sum(1 for r in rows if r['result'] in SAVE_CODES),
            "er": sum(r['er'] or 0 for r in rows),
            "so": sum(r['so'] or 0 for r in rows),
            "h":  sum(r['h'] or 0 for r in rows),
            "bb": sum(r['bb'] or 0 for r in rows),
            "ip": outs_to_ip(outs),
        }
        if outs:
            s["era"] = f"{s['er']*27/outs:.2f}"
            s["whip"] = f"{(s['bb']+s['h'])*3/outs:.2f}"
        return s

    def get_player_info(name):
        row = _query(conn, "SELECT * FROM players WHERE name=? LIMIT 1", (name,), one=True)
        return dict(row) if row else {"name": name, "position": ""}

    def is_pitcher(name, info):
        if info.get("position"):
            return info["position"] == "투수"
        # 선수단에 없는 선수(이적/은퇴)는 기록으로 판단
        pc = _query(conn, "SELECT COUNT(*) c FROM pitcher_stats WHERE name=?", (name,), one=True)
        bc = _query(conn, "SELECT COUNT(*) c FROM batter_stats WHERE name=?", (name,), one=True)
        return (pc and pc['c'] or 0) > (bc and bc['c'] or 0)

    info1, info2 = get_player_info(p1), get_player_info(p2)
    is_pitcher1, is_pitcher2 = is_pitcher(p1, info1), is_pitcher(p2, info2)
    stats1 = get_pitcher(p1) if is_pitcher1 else get_batter(p1)
    stats2 = get_pitcher(p2) if is_pitcher2 else get_batter(p2)
    conn.close()

    return jsonify({
        "p1": {"info": info1, "stats": stats1, "is_pitcher": is_pitcher1},
        "p2": {"info": info2, "stats": stats2, "is_pitcher": is_pitcher2},
        "year": year,
    })


def _num_sort_key(p):
    num = str(p.get('number') or '')
    return int(num) if num.isdigit() else 999


@app.route("/players")
def players_page():
    conn = get_connection()
    # CAST(number AS INTEGER)는 PostgreSQL에서 빈 문자열이면 오류 → 정렬은 파이썬에서
    players = [dict(p) for p in _query(conn, "SELECT * FROM players")]
    players.sort(key=lambda p: (p.get('team_level') or '', p.get('position') or '', _num_sort_key(p)))
    updated_at = _query(conn, "SELECT updated_at FROM players ORDER BY updated_at DESC LIMIT 1", one=True)

    # 당일 등록/말소 (players_daily_change: date, change_type, player_name, detail, created_at)
    today = datetime.now().strftime("%Y-%m-%d")
    daily_changes = [dict(d) for d in _query(conn,
        "SELECT * FROM players_daily_change WHERE date=? ORDER BY change_type, player_name", (today,))]
    conn.close()

    return render_template("players.html",
        players=players,
        updated_at=updated_at["updated_at"][:10] if updated_at and updated_at["updated_at"] else "미업데이트",
        daily_changes=daily_changes,
    )


@app.route("/games")
def games_all():
    conn = get_connection()
    games = _query(conn, "SELECT * FROM games ORDER BY date DESC, game_id DESC")
    futures_games = _query(conn, "SELECT * FROM futures_games ORDER BY date DESC, game_id DESC")
    conn.close()

    # 시즌 목록 추출
    years = sorted(set(g['date'][:4] for g in games if g['date']), reverse=True)
    fut_years = sorted(set(g['date'][:4] for g in futures_games if g['date']), reverse=True)

    return render_template("games.html",
        games=[dict(g) for g in games],
        futures_games=[dict(g) for g in futures_games],
        years=years,
        fut_years=fut_years,
        current_year=str(datetime.now().year),
    )


@app.route("/game/<game_id>")
def game_report(game_id):
    detail = get_game_detail(game_id)
    if not detail.get("game"):
        abort(404)
    return render_template("game.html", detail=detail)


# 시즌별 집계
def aggregate_by_season_pitcher(stats):
    seasons = {}
    for d in stats:
        yr = d['date'][:4]
        if yr not in seasons:
            seasons[yr] = {'year': yr, 'games': 0, 'wins': 0, 'loses': 0, 'holds': 0, 'saves': 0,
                           'er': 0, 'so': 0, 'bb': 0, 'h': 0, 'hr': 0, 'ip_outs': 0, 'ab_against': 0}
        s = seasons[yr]
        s['games'] += 1
        if d.get('result') == '승': s['wins'] += 1
        elif d.get('result') == '패': s['loses'] += 1
        elif d.get('result') in HOLD_CODES: s['holds'] += 1
        elif d.get('result') in SAVE_CODES: s['saves'] += 1
        for k in ('er', 'so', 'bb', 'h', 'hr', 'ab_against'):
            s[k] += d.get(k) or 0
        s['ip_outs'] += ip_to_outs(d.get('ip'))
    for s in seasons.values():
        o = s['ip_outs']
        s['ip'] = outs_to_ip(o)
        s['era'] = f"{s['er']*27/o:.2f}" if o else "-"
        s['whip'] = f"{(s['bb']+s['h'])*3/o:.2f}" if o else "-"
        # 피안타율: 피안타 / 상대 타수 (퓨처스처럼 상대 타수가 없으면 대면 타자 근사)
        denom = s['ab_against'] or (o + s['h'])
        s['bavg'] = fmt_rate(s['h']/denom) if denom else "-"
    return sorted(seasons.values(), key=lambda x: x['year'], reverse=True)


def aggregate_by_season_batter(stats):
    seasons = {}
    for d in stats:
        yr = d['date'][:4]
        if yr not in seasons:
            seasons[yr] = {'year': yr, 'games': 0, 'ab': 0, 'h': 0, 'hr': 0, 'doubles': 0, 'triples': 0,
                           'rbi': 0, 'bb': 0, 'so': 0, 'r': 0}
        s = seasons[yr]
        s['games'] += 1
        for k in ('ab', 'h', 'hr', 'doubles', 'triples', 'rbi', 'bb', 'so', 'r'):
            s[k] += d.get(k) or 0
    for s in seasons.values():
        yr = s['year']
        ab, h, hr, bb = s['ab'], s['h'], s['hr'], s['bb']
        doubles, triples = s['doubles'], s['triples']
        s['avg'] = fmt_rate(h/ab) if ab > 0 else ".000"
        obp_f = (h+bb)/(ab+bb) if (ab+bb) > 0 else 0
        s['obp'] = fmt_rate(obp_f)
        # SLG = (단타 + 2루타*2 + 3루타*3 + 홈런*4) / 타수
        singles = max(h - doubles - triples - hr, 0)
        tb = singles + doubles*2 + triples*3 + hr*4
        slg_f = tb/ab if ab > 0 else 0
        s['slg'] = fmt_rate(slg_f)
        s['ops'] = fmt_rate(obp_f+slg_f)
        # wOBA / wRC+
        woba = calc_woba(ab, h, doubles, triples, hr, bb, year=int(yr))
        s['woba'] = fmt_rate(woba)
        s['wrc_plus'] = calc_wrc_plus(woba, year=int(yr)) if (ab + bb) else '-'
    return sorted(seasons.values(), key=lambda x: x['year'], reverse=True)


@app.route("/player/<pname>")
def player_page(pname):
    conn = get_connection()

    player_info = _query(conn,
        "SELECT * FROM players WHERE name=? ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END LIMIT 1",
        (pname,), one=True)
    player_info = dict(player_info) if player_info else {}

    # players 테이블에 없으면 batter_stats에서 포지션 추출
    if not player_info:
        pos_row = _query(conn,
            "SELECT position FROM batter_stats WHERE name=? AND position != '' LIMIT 1", (pname,), one=True)
        if pos_row:
            pos = pos_row["position"]
            player_info = {"name": pname,
                           "position": "외야수" if pos in ("좌", "중", "우", "외야수")
                           else "내야수" if pos in ("一", "二", "三", "유", "내야수")
                           else "포수" if pos in ("포", "포수") else pos,
                           "number": "", "batting": "", "birth": "", "height_weight": "", "team_level": ""}

    # 1군 기록 (KBO 정규시즌)
    batter_stats = [dict(r) for r in _query(conn, """
        SELECT b.*, g.date, g.result, g.home_team, g.away_team, '1군' as league
        FROM batter_stats b JOIN games g ON b.game_id = g.game_id
        WHERE b.name = ? ORDER BY g.date DESC
    """, (pname,))]
    pitcher_stats = [dict(r) for r in _query(conn, """
        SELECT p.*, g.date, g.result AS game_result, g.home_team, g.away_team, '1군' as league
        FROM pitcher_stats p JOIN games g ON p.game_id = g.game_id
        WHERE p.name = ? ORDER BY g.date DESC
    """, (pname,))]

    # 퓨처스 기록
    futures_batter = [dict(r) for r in _query(conn, """
        SELECT b.*, g.date, g.result, g.home_team, g.away_team, '퓨처스' as league
        FROM futures_batter_stats b JOIN futures_games g ON b.game_id = g.game_id
        WHERE b.name = ? ORDER BY g.date DESC
    """, (pname,))]
    futures_pitcher = [dict(r) for r in _query(conn, """
        SELECT p.*, g.date, g.result AS game_result, g.home_team, g.away_team, '퓨처스' as league
        FROM futures_pitcher_stats p JOIN futures_games g ON p.game_id = g.game_id
        WHERE p.name = ? ORDER BY g.date DESC
    """, (pname,))]

    ai_reports = [dict(r) for r in _query(conn,
        "SELECT * FROM ai_reports WHERE player_name=? AND report_type='player' ORDER BY created_at DESC",
        (pname,))]
    # 시즌별 AI 평가 (report_type: player_season_{연도}_{리그})
    season_ai_reports = [dict(r) for r in _query(conn,
        "SELECT * FROM ai_reports WHERE player_name=? AND report_type LIKE ? ORDER BY created_at DESC",
        (pname, 'player_season%'))]
    conn.close()

    if not batter_stats and not pitcher_stats and not futures_batter and not futures_pitcher and not player_info:
        abort(404)

    # 포지션 기반으로 투수/타자 판단 (players 테이블 우선)
    if player_info.get("position"):
        is_pitcher = player_info["position"] == "투수"
    else:
        is_pitcher = len(pitcher_stats) + len(futures_pitcher) > len(batter_stats) + len(futures_batter)

    kbo_seasons = (aggregate_by_season_pitcher(pitcher_stats) if is_pitcher
                   else aggregate_by_season_batter(batter_stats))
    fut_seasons = (aggregate_by_season_pitcher(futures_pitcher) if is_pitcher
                   else aggregate_by_season_batter(futures_batter))

    for r in season_ai_reports:
        parts = r['report_type'].split('_')  # player_season_2025_kbo
        r['label'] = (f"{parts[2]}시즌 · {'KBO' if parts[3] == 'kbo' else '퓨처스'}"
                      if len(parts) >= 4 else "시즌")

    return render_template("player.html",
        name=pname,
        player_info=player_info,
        is_pitcher=is_pitcher,
        kbo_games=pitcher_stats if is_pitcher else batter_stats,
        fut_games=futures_pitcher if is_pitcher else futures_batter,
        kbo_seasons=kbo_seasons,
        fut_seasons=fut_seasons,
        ai_reports=ai_reports,
        season_ai_reports=season_ai_reports,
        current_year=str(datetime.now().year),
    )


# ──────────────────────────────────────────
# API 라우터
# ──────────────────────────────────────────

@app.route("/api/games")
def api_games():
    games = get_recent_games(limit=10)
    return jsonify(games)


@app.route("/api/game/<game_id>")
def api_game(game_id):
    detail = get_game_detail(game_id)
    if not detail.get("game"):
        abort(404)
    return jsonify(detail)


@app.route("/api/player/<pname>")
def api_player(pname):
    conn = get_connection()
    player = _query(conn, "SELECT * FROM players WHERE name=? LIMIT 1", (pname,), one=True)
    batter = _query(conn, """
        SELECT b.*, g.date FROM batter_stats b JOIN games g ON b.game_id=g.game_id
        WHERE b.name=? ORDER BY g.date DESC
    """, (pname,))
    pitcher = _query(conn, """
        SELECT p.*, g.date FROM pitcher_stats p JOIN games g ON p.game_id=g.game_id
        WHERE p.name=? ORDER BY g.date DESC
    """, (pname,))
    conn.close()
    if not batter and not pitcher and not player:
        abort(404)
    return jsonify({
        "player":  dict(player) if player else {},
        "batter":  [dict(r) for r in batter],
        "pitcher": [dict(r) for r in pitcher],
    })


# ──────────────────────────────────────────
# AI 분석 API
# ──────────────────────────────────────────

@app.route("/api/analyze/<game_id>", methods=["POST"])
def api_analyze(game_id):
    try:
        from analyzer import analyze_all
        detail = get_game_detail(game_id)
        if not detail.get("game"):
            return jsonify({"error": "경기 데이터 없음"}), 404
        analyze_all(game_id)
        updated = get_game_detail(game_id)
        return jsonify({"success": True, "reports": updated.get("reports", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/game/<game_id>", methods=["POST"])
def api_analyze_game(game_id):
    try:
        # 이미 생성된 경기 분석이 있으면 재사용 (중복 API 호출 방지)
        detail = get_game_detail(game_id)
        if not detail.get("game"):
            return jsonify({"error": "경기 데이터 없음"}), 404
        existing = [r for r in detail.get("reports", []) if r.get("report_type") == "game"]
        if existing:
            return jsonify({"success": True, "content": existing[-1]["content"], "cached": True})
        from analyzer import analyze_game
        content = analyze_game(game_id)
        return jsonify({"success": True, "content": content, "cached": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/player-season", methods=["POST"])
def api_analyze_player_season():
    try:
        data = request.get_json(silent=True) or {}
        player_name = data.get("player_name")
        is_pitcher  = data.get("is_pitcher", False)
        year        = str(data.get("year") or "")  # 특정 시즌 지정
        league      = data.get("league", "kbo")    # kbo or fut
        if league != "kbo":
            league = "fut"  # 기존 저장 키(player_season_{연도}_fut)와 호환
        if not player_name:
            return jsonify({"error": "선수명 없음"}), 400
        if year and not (year.isdigit() and len(year) == 4):
            return jsonify({"error": "잘못된 연도"}), 400

        # 이미 생성된 시즌 분석 확인
        conn = get_connection()
        report_key = f"player_season_{year}_{league}" if year else "player_season"
        existing = _query(conn,
            "SELECT content FROM ai_reports WHERE player_name=? AND report_type=? ORDER BY created_at DESC LIMIT 1",
            (player_name, report_key), one=True)
        if existing:
            conn.close()
            return jsonify({"success": True, "content": existing["content"], "cached": True})

        season_label = f"{year}시즌" if year else "이번 시즌"
        league_label = "KBO" if league == "kbo" else "퓨처스리그"
        join = "games" if league == "kbo" else "futures_games"
        year_filter = "AND g.date LIKE ?" if year else ""
        params = (player_name,) + ((f"{year}%",) if year else ())

        if is_pitcher:
            table = "pitcher_stats" if league == "kbo" else "futures_pitcher_stats"
            stats = [dict(r) for r in _query(conn, f"""
                SELECT p.*, g.date FROM {table} p
                JOIN {join} g ON p.game_id = g.game_id
                WHERE p.name = ? {year_filter} ORDER BY g.date DESC
            """, params)]
            if not stats:
                conn.close()
                return jsonify({"error": f"{season_label} {league_label} 기록이 없어요"}), 404
            season = aggregate_by_season_pitcher(stats)[0] if year else None
            lines = [f"{s['date'][4:6]}/{s['date'][6:]} {s['ip']}이닝 {s['er']}자책 {s['so']}삼진 ERA {s['era']}" for s in stats]
            stat_summary = "\n".join(lines[:30])
            totals = (f"총 {len(stats)}경기 등판, {season['ip']}이닝, 자책점 {season['er']}점, 삼진 {season['so']}개, "
                      f"ERA {season['era']}, WHIP {season['whip']}" if season else
                      f"총 {len(stats)}경기 등판, 자책점 {sum(s['er'] for s in stats)}점, 삼진 {sum(s['so'] for s in stats)}개")
            prompt = f"""두산 베어스 투수 {player_name}의 {season_label} {league_label} 전체 기록을 분석해주세요.

기록 목록:
{stat_summary}

{totals}

3~4문단으로 시즌 전체 흐름 평가, 강점, 약점, 발전 방향을 팬 입장에서 따뜻하게 작성해주세요."""
        else:
            table = "batter_stats" if league == "kbo" else "futures_batter_stats"
            stats = [dict(r) for r in _query(conn, f"""
                SELECT b.*, g.date FROM {table} b
                JOIN {join} g ON b.game_id = g.game_id
                WHERE b.name = ? {year_filter} ORDER BY g.date DESC
            """, params)]
            if not stats:
                conn.close()
                return jsonify({"error": f"{season_label} {league_label} 기록이 없어요"}), 404
            total_ab  = sum(s['ab'] for s in stats)
            total_h   = sum(s['h'] for s in stats)
            total_hr  = sum(s['hr'] for s in stats)
            total_rbi = sum(s['rbi'] for s in stats)
            avg = f"{total_h/total_ab:.3f}" if total_ab > 0 else ".000"
            prompt = f"""두산 베어스 타자 {player_name}의 {season_label} {league_label} 전체 기록을 분석해주세요.

시즌 누적: {total_ab}타수 {total_h}안타 {total_hr}홈런 {total_rbi}타점 타율 {avg}
총 {len(stats)}경기 출장

3~4문단으로 시즌 전체 흐름 평가, 강점, 약점, 발전 방향을 팬 입장에서 따뜻하게 작성해주세요."""

        from analyzer import _call_claude
        result = _call_claude(prompt, max_tokens=2048)

        conn.execute(
            "INSERT INTO ai_reports (game_id, report_type, player_name, content, created_at) VALUES ('season', ?, ?, ?, ?)",
            (report_key, player_name, result, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "content": result, "cached": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/player/<game_id>", methods=["POST"])
def api_analyze_player(game_id):
    try:
        player_name = (request.get_json(silent=True) or {}).get("player_name")
        if not player_name:
            return jsonify({"error": "선수명 없음"}), 400

        conn = get_connection()
        existing = _query(conn,
            "SELECT content FROM ai_reports WHERE game_id=? AND report_type='player' AND player_name=? ORDER BY created_at DESC LIMIT 1",
            (game_id, player_name), one=True)
        conn.close()

        if existing:
            return jsonify({"success": True, "content": existing["content"], "player_name": player_name, "cached": True})

        from analyzer import analyze_player
        content = analyze_player(game_id, player_name)
        return jsonify({"success": True, "content": content, "player_name": player_name, "cached": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ai-reports")
def ai_reports_page():
    """AI 분석 목록 페이지"""
    conn = get_connection()
    reports = _query(conn, """
        SELECT r.*, g.date, g.home_team, g.away_team, g.home_score, g.away_score, g.result
        FROM ai_reports r
        LEFT JOIN games g ON r.game_id = g.game_id
        ORDER BY r.created_at DESC
    """)
    conn.close()
    return render_template("ai_reports.html", reports=[dict(r) for r in reports])


@app.route("/api/ai-reports")
def api_ai_reports():
    """AI 분석 목록 JSON"""
    conn = get_connection()
    reports = _query(conn, """
        SELECT r.id, r.game_id, r.report_type, r.player_name, r.content, r.created_at,
               g.date, g.home_team, g.away_team, g.home_score, g.away_score, g.result
        FROM ai_reports r
        LEFT JOIN games g ON r.game_id = g.game_id
        ORDER BY r.created_at DESC
    """)
    conn.close()
    return jsonify([dict(r) for r in reports])


# ──────────────────────────────────────────
# 모바일 앱 API 엔드포인트
# ──────────────────────────────────────────

@app.route("/api/games/recent")
def api_recent_games():
    limit = min(max(request.args.get("limit", 10, type=int), 1), 200)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM games ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/games/calendar")
def api_games_calendar():
    year  = request.args.get("year", str(datetime.now().year))
    month = request.args.get("month", str(datetime.now().month)).zfill(2)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM games WHERE date LIKE ? ORDER BY date",
            (f"{year}{month}%",)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/next-game")
def api_next_game():
    data = cached_next_game()
    return jsonify(data if data else {})


@app.route("/api/players")
def api_players():
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM players WHERE status='active'").fetchall()]
        rows.sort(key=lambda p: (p.get('team_level') or '', p.get('position') or '', _num_sort_key(p)))
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/stats/team")
def api_team_stats():
    year = request.args.get("year", str(datetime.now().year))
    conn = get_connection()
    try:
        s = _team_season_stats(conn, year)
        return jsonify({k: s[k] for k in ("year", "wins", "loses", "draws", "avg", "hr", "rbi", "era", "so_pit")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ──────────────────────────────────────────
# 에러 페이지
# ──────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "찾을 수 없음"}), 404
    return render_template("error.html", code=404, message="페이지를 찾을 수 없어요."), 404


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "서버 오류"}), 500
    return render_template("error.html", code=500, message="일시적인 서버 오류가 발생했어요."), 500


# ──────────────────────────────────────────
# 스케줄러
# ──────────────────────────────────────────

def start_scheduler_thread():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from scheduler import run_crawl_job

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_crawl_job,
        trigger=CronTrigger(hour="16,17,18,19,20,21,22,23", minute="0,30", timezone="Asia/Seoul"),
        id="kbo_crawl", max_instances=1, misfire_grace_time=300,
    )
    scheduler.start()
    print("백그라운드 스케줄러 시작")


_scheduler_started = False
_scheduler_lock = threading.Lock()

def ensure_scheduler():
    global _scheduler_started
    with _scheduler_lock:
        if not _scheduler_started:
            start_scheduler_thread()
            _scheduler_started = True

with app.app_context():
    ensure_scheduler()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") != "production"
    print(f"서버 시작 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
