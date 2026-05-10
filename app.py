"""
두산 베어스 분석 웹사이트 - Flask 웹서버
"""

import os
import threading
from flask import Flask, render_template, jsonify, abort, request
from dotenv import load_dotenv
from database import init_db, get_recent_games, get_game_detail, get_player_stats

load_dotenv()
init_db()


# KBO 리그 연도별 wOBA 상수 (매년 업데이트)
KBO_WOBA_CONSTANTS = {
    2023: {"woba_avg": 0.320, "woba_scale": 1.21, "r_pa": 0.123, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
    2024: {"woba_avg": 0.325, "woba_scale": 1.22, "r_pa": 0.127, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
    2025: {"woba_avg": 0.323, "woba_scale": 1.21, "r_pa": 0.125, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
    2026: {"woba_avg": 0.323, "woba_scale": 1.21, "r_pa": 0.125, "w_bb": 0.69, "w_1b": 0.89, "w_2b": 1.27, "w_3b": 1.62, "w_hr": 2.10},
}

def calc_woba(ab, h, doubles, triples, hr, bb, year=None):
    """wOBA 계산"""
    from datetime import datetime
    yr = year or datetime.now().year
    c = KBO_WOBA_CONSTANTS.get(yr, KBO_WOBA_CONSTANTS[2025])
    singles = h - doubles - triples - hr
    denom = ab + bb
    if denom == 0:
        return 0.0
    return (c["w_bb"]*bb + c["w_1b"]*singles + c["w_2b"]*doubles + c["w_3b"]*triples + c["w_hr"]*hr) / denom

def calc_wrc_plus(woba, year=None):
    """wRC+ 계산 (100=리그평균, 150=평균보다 50% 좋음)"""
    from datetime import datetime
    yr = year or datetime.now().year
    c = KBO_WOBA_CONSTANTS.get(yr, KBO_WOBA_CONSTANTS[2025])
    if c["r_pa"] == 0:
        return 100
    wrc_plus = ((woba - c["woba_avg"]) / c["woba_scale"] + c["r_pa"]) / c["r_pa"] * 100
    return round(wrc_plus)

app = Flask(__name__)


# ──────────────────────────────────────────
# 페이지 라우터
# ──────────────────────────────────────────

@app.route("/")
def index():
    from database import get_connection, get_recent_futures_games
    games = get_recent_games(limit=5)
    futures_games = get_recent_futures_games(limit=5)

    # 다음 경기 예고
    try:
        from kbo_crawler import get_next_game
        next_game = get_next_game()
    except:
        next_game = None

    # 팀 시즌 스탯 집계
    from datetime import datetime as _dt
    year = str(_dt.now().year)
    conn = get_connection()
    try:
        # 타자 스탯
        bat = conn.execute("""
            SELECT SUM(ab) ab, SUM(h) h, SUM(hr) hr, SUM(rbi) rbi, SUM(bb) bb, SUM(so) so
            FROM batter_stats b JOIN games g ON b.game_id = g.game_id
            WHERE g.date LIKE ?
        """, (year+'%',)).fetchone()
        # 투수 스탯
        pit = conn.execute("""
            SELECT SUM(er) er, SUM(so) so, COUNT(DISTINCT g.game_id) games
            FROM pitcher_stats p JOIN games g ON p.game_id = g.game_id
            WHERE g.date LIKE ?
        """, (year+'%',)).fetchone()
        # 승/패
        wl = conn.execute("""
            SELECT result, COUNT(*) cnt FROM games
            WHERE date LIKE ? AND result IN ('승','패','무')
            GROUP BY result
        """, (year+'%',)).fetchall()
    except:
        bat = pit = None
        wl = []
    conn.close()

    wl_dict = {r['result']: r['cnt'] for r in wl}
    wins  = wl_dict.get('승', 0)
    loses = wl_dict.get('패', 0)
    draws = wl_dict.get('무', 0)
    team_avg = f"{bat['h']/bat['ab']:.3f}" if bat and bat['ab'] else ".000"
    ip_games = pit['games'] if pit and pit['games'] else 1
    team_era = f"{(pit['er']*9)/(ip_games*9**(0)):.2f}" if False else "-"
    # ERA 계산 (이닝 합산 필요 - 간단히 경기당 자책으로 근사)
    era_val  = f"{pit['er']/ip_games*9:.2f}" if pit and ip_games else "-"

    team_stats = {
        "wins": wins, "loses": loses, "draws": draws,
        "avg": team_avg,
        "hr":  bat['hr'] if bat else 0,
        "rbi": bat['rbi'] if bat else 0,
        "bb":  bat['bb'] if bat else 0,
        "so_bat": bat['so'] if bat else 0,
        "era": era_val,
        "so_pit": pit['so'] if pit else 0,
    }

    return render_template("index.html", games=games, futures_games=futures_games, team_stats=team_stats, next_game=next_game)


@app.route("/compare")
def compare_page():
    """선수 비교 페이지"""
    from database import get_connection
    from datetime import datetime as _dt
    conn = get_connection()
    try:
        # 포지션 4가지로 단순화
        def simplify_pos(pos):
            if not pos: return '기타'
            if pos in ('투수',): return '투수'
            if pos in ('포수',): return '포수'
            if pos in ('1루수','2루수','3루수','유격수','내야수'): return '내야수'
            if pos in ('좌익수','우익수','중견수','외야수'): return '외야수'
            return '내야수'  # 지명타자 등은 내야수로

        # 시즌별 선수 목록 (API에서 year 파라미터로 필터)
        current_year = str(_dt.now().year)
        target_year = request.args.get('year', current_year)

        batters_raw = conn.execute(
            """SELECT DISTINCT b.name, b.position
               FROM batter_stats b JOIN games g ON b.game_id=g.game_id
               WHERE substr(g.date,1,4)=? ORDER BY b.name""",
            (target_year,)
        ).fetchall()
        pitchers_raw = conn.execute(
            """SELECT DISTINCT p.name, '투수' as position
               FROM pitcher_stats p JOIN games g ON p.game_id=g.game_id
               WHERE substr(g.date,1,4)=? ORDER BY p.name""",
            (target_year,)
        ).fetchall()

        seen = set()
        players = []
        for p in list(batters_raw) + list(pitchers_raw):
            if p['name'] not in seen:
                seen.add(p['name'])
                players.append({'name': p['name'], 'position': simplify_pos(p['position'])})
        players = sorted(players, key=lambda x: (x['position'], x['name']))
        years = conn.execute(
            "SELECT DISTINCT substr(date,1,4) yr FROM games ORDER BY yr DESC"
        ).fetchall()
        years = [r['yr'] for r in years]
    except:
        players = []
        years = [str(_dt.now().year)]
    conn.close()
    return render_template("compare.html",
        players=[dict(p) for p in players],
        years=years,
        current_year=str(_dt.now().year),
    )


@app.route("/api/compare")
def api_compare():
    """두 선수 스탯 비교 JSON"""
    from database import get_connection
    from datetime import datetime as _dt
    p1 = request.args.get("p1", "")
    p2 = request.args.get("p2", "")
    year = request.args.get("year", str(_dt.now().year))
    if not year:
        year = str(_dt.now().year)
    if not p1 or not p2:
        return jsonify({"error": "선수명 필요"}), 400

    conn = get_connection()

    def get_batter(name):
        rows = conn.execute("""
            SELECT SUM(ab) ab, SUM(h) h, SUM(hr) hr, SUM(rbi) rbi,
                   SUM(bb) bb, SUM(so) so, COUNT(*) games
            FROM batter_stats b JOIN games g ON b.game_id = g.game_id
            WHERE b.name=? AND g.date LIKE ?
        """, (name, year+'%')).fetchone()
        return dict(rows) if rows else {}

    def get_pitcher(name):
        rows = conn.execute("""
            SELECT SUM(p.er) er, SUM(p.so) so, SUM(p.h) h, SUM(p.bb) bb,
                   COUNT(*) games,
                   SUM(CASE WHEN p.result='승' THEN 1 ELSE 0 END) wins,
                   SUM(CASE WHEN p.result='패' THEN 1 ELSE 0 END) loses,
                   SUM(CASE WHEN p.result='홀드' THEN 1 ELSE 0 END) holds,
                   SUM(CASE WHEN p.result='세이브' THEN 1 ELSE 0 END) saves
            FROM pitcher_stats p JOIN games g ON p.game_id = g.game_id
            WHERE p.name=? AND g.date LIKE ?
        """, (name, year+'%')).fetchone()
        return dict(rows) if rows else {}

    def get_player_info(name):
        row = conn.execute("SELECT * FROM players WHERE name=? LIMIT 1", (name,)).fetchone()
        return dict(row) if row else {"name": name, "position": ""}

    info1 = get_player_info(p1)
    info2 = get_player_info(p2)
    is_pitcher1 = info1.get("position") == "투수"
    is_pitcher2 = info2.get("position") == "투수"

    stats1 = get_pitcher(p1) if is_pitcher1 else get_batter(p1)
    stats2 = get_pitcher(p2) if is_pitcher2 else get_batter(p2)

    # 타율 계산
    if not is_pitcher1 and stats1.get("ab"):
        stats1["avg"] = f"{stats1['h']/stats1['ab']:.3f}"
    if not is_pitcher2 and stats2.get("ab"):
        stats2["avg"] = f"{stats2['h']/stats2['ab']:.3f}"

    conn.close()
    return jsonify({
        "p1": {"info": info1, "stats": stats1, "is_pitcher": is_pitcher1},
        "p2": {"info": info2, "stats": stats2, "is_pitcher": is_pitcher2},
        "year": year,
    })


@app.route("/players")
def players_page():
    from database import get_connection
    conn = get_connection()
    try:
        players = conn.execute(
            "SELECT * FROM players ORDER BY team_level, position, CAST(number AS INTEGER)"
        ).fetchall()
        updated_at = conn.execute(
            "SELECT updated_at FROM players ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    except:
        players = []
        updated_at = None
    # 당일 등록/말소 (오늘 날짜 것만)
    from datetime import datetime as _dt
    today = _dt.now().strftime("%Y-%m-%d")
    try:
        daily_changes = conn.execute(
            "SELECT * FROM players_daily_change WHERE updated_at LIKE ? ORDER BY change_type, team_level",
            (today + '%',)
        ).fetchall()
        daily_changes = [dict(d) for d in daily_changes]
    except:
        daily_changes = []

    conn.close()
    return render_template("players.html",
        players=[dict(p) for p in players],
        updated_at=updated_at["updated_at"][:10] if updated_at else "미업데이트",
        daily_changes=daily_changes,
    )


@app.route("/games")
def games_all():
    from database import get_connection, get_recent_futures_games
    from datetime import datetime as _dt

    conn = get_connection()
    try:
        games = conn.execute(
            "SELECT * FROM games ORDER BY date DESC LIMIT 500"
        ).fetchall()
        futures_games = conn.execute(
            "SELECT * FROM futures_games ORDER BY date DESC LIMIT 500"
        ).fetchall()
    except:
        games = []
        futures_games = []
    conn.close()

    # 시즌 목록 추출
    years = sorted(set(g['date'][:4] for g in games if g['date']), reverse=True)
    fut_years = sorted(set(g['date'][:4] for g in futures_games if g['date']), reverse=True)

    return render_template("games.html",
        games=[dict(g) for g in games],
        futures_games=[dict(g) for g in futures_games],
        years=years,
        fut_years=fut_years,
        current_year=str(_dt.now().year),
    )


@app.route("/game/<game_id>")
def game_report(game_id):
    detail = get_game_detail(game_id)
    if not detail.get("game"):
        abort(404)
    return render_template("game.html", detail=detail)


@app.route("/player/<pname>")
def player_page(pname):
    from database import get_connection
    conn = get_connection()

    try:
        player_info = conn.execute(
            "SELECT * FROM players WHERE name=? ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END LIMIT 1", (pname,)
        ).fetchone()
        player_info = dict(player_info) if player_info else {}
    except:
        player_info = {}

    # players 테이블에 없으면 batter/pitcher stats에서 포지션 추출
    if not player_info:
        try:
            pos_row = conn.execute(
                "SELECT position FROM batter_stats WHERE name=? AND position != '' LIMIT 1", (pname,)
            ).fetchone()
            if pos_row:
                player_info = {"name": pname, "position": "외야수" if pos_row[0] in ("좌","중","우","외야수") 
                               else "내야수" if pos_row[0] in ("一","二","三","유","내야수") 
                               else "포수" if pos_row[0] in ("포","포수") else pos_row[0], 
                               "number": "", "batting": "", "birth": "", "height_weight": "", "team_level": ""}
        except:
            pass

    # 1군 기록 (KBO 정규시즌)
    batter_stats = conn.execute("""
        SELECT b.*, g.date, g.result, g.home_team, g.away_team, '1군' as league
        FROM batter_stats b JOIN games g ON b.game_id = g.game_id
        WHERE b.name = ? ORDER BY g.date DESC
    """, (pname,)).fetchall()

    pitcher_stats = conn.execute("""
        SELECT p.*, g.date, g.result, g.home_team, g.away_team, '1군' as league
        FROM pitcher_stats p JOIN games g ON p.game_id = g.game_id
        WHERE p.name = ? ORDER BY g.date DESC
    """, (pname,)).fetchall()

    # 퓨처스 기록 (있을 경우)
    try:
        futures_batter = conn.execute("""
            SELECT b.*, g.date, g.result, g.home_team, g.away_team, '퓨처스' as league
            FROM futures_batter_stats b JOIN futures_games g ON b.game_id = g.game_id
            WHERE b.name = ? ORDER BY g.date DESC
        """, (pname,)).fetchall()
    except:
        futures_batter = []

    try:
        futures_pitcher = conn.execute("""
            SELECT p.*, g.date, g.result, g.home_team, g.away_team, '퓨처스' as league
            FROM futures_pitcher_stats p JOIN futures_games g ON p.game_id = g.game_id
            WHERE p.name = ? ORDER BY g.date DESC
        """, (pname,)).fetchall()
    except:
        futures_pitcher = []

    ai_reports = conn.execute(
        "SELECT * FROM ai_reports WHERE player_name=? AND report_type='player' ORDER BY created_at DESC",
        (pname,)
    ).fetchall()

    try:
        player_season_report = conn.execute(
            "SELECT * FROM ai_reports WHERE player_name=? AND report_type='player_season' ORDER BY created_at DESC LIMIT 1",
            (pname,)
        ).fetchone()
        player_season_report = dict(player_season_report) if player_season_report else None
    except:
        player_season_report = None

    conn.close()

    if not batter_stats and not pitcher_stats and not player_info:
        abort(404)

    # 포지션 기반으로 투수/타자 판단 (players 테이블 우선)
    if player_info and player_info.get("position"):
        is_pitcher = player_info["position"] == "투수"
    else:
        is_pitcher = len(pitcher_stats) > len(batter_stats)

    # 현재 시즌 연도
    from datetime import datetime as _dt
    current_year = str(_dt.now().year)

    # 시즌별 집계
    def aggregate_by_season_pitcher(stats):
        seasons = {}
        for p in stats:
            yr = p['date'][:4] if isinstance(p, dict) else p[0][:4]
            d = dict(p) if not isinstance(p, dict) else p
            if yr not in seasons:
                seasons[yr] = {'year': yr, 'games':0, 'wins':0, 'loses':0, 'holds':0, 'saves':0,
                               'er':0, 'so':0, 'bb':0, 'h':0, 'hr':0, 'ip_outs':0}
            s = seasons[yr]
            s['games'] += 1
            if d.get('result') == '승': s['wins'] += 1
            elif d.get('result') == '패': s['loses'] += 1
            elif d.get('result') in ('홀드', 'H'): s['holds'] += 1
            elif d.get('result') in ('세이브', '세', 'S'): s['saves'] += 1
            s['er'] += d.get('er', 0)
            s['so'] += d.get('so', 0)
            s['bb'] += d.get('bb', 0)
            s['h']  += d.get('h', 0)
            s['hr'] += d.get('hr', 0)
            # IP 계산 (1 1/3 → outs)
            ip = str(d.get('ip', '0'))
            try:
                parts = ip.split()
                outs = 0
                for part in parts:
                    if '/' in part:
                        n, d2 = part.split('/')
                        outs += int(n) * (3 // int(d2))
                    else:
                        outs += int(part) * 3
                s['ip_outs'] += outs
            except: pass
        for s in seasons.values():
            o = s['ip_outs']
            s['ip'] = f"{o//3}.{o%3}" if o > 0 else "0"
            ip_inn = o/3 if o > 0 else 0
            s['era']  = f"{s['er']*9/ip_inn:.2f}" if ip_inn > 0 else "-"
            s['whip'] = f"{(s['bb']+s['h'])/ip_inn:.2f}" if ip_inn > 0 else "-"
            # 피안타율: 피안타 / (상대타자 - 볼넷) 근사
            bf_approx = s['h'] + s['bb'] + s['so'] + s['er']  # 대략적 대면타자
            s['bavg'] = f"{s['h']/bf_approx:.3f}" if bf_approx > 0 else ".000"
        return sorted(seasons.values(), key=lambda x: x['year'], reverse=True)

    def aggregate_by_season_batter(stats):
        seasons = {}
        for b in stats:
            d = dict(b) if not isinstance(b, dict) else b
            yr = d['date'][:4]
            if yr not in seasons:
                seasons[yr] = {'year': yr, 'games':0, 'ab':0, 'h':0, 'hr':0, 'doubles':0, 'triples':0, 'rbi':0, 'bb':0, 'so':0, 'r':0}
            s = seasons[yr]
            s['games']   += 1
            s['ab']      += d.get('ab', 0)
            s['h']       += d.get('h', 0)
            s['hr']      += d.get('hr', 0)
            s['doubles'] += d.get('doubles', 0)
            s['triples'] += d.get('triples', 0)
            s['rbi']     += d.get('rbi', 0)
            s['bb']      += d.get('bb', 0)
            s['so']      += d.get('so', 0)
            s['r']       += d.get('r', 0)
        for s in seasons.values():
            ab, h, hr, bb = s['ab'], s['h'], s['hr'], s['bb']
            doubles = s.get('doubles', 0) or 0
            triples = s.get('triples', 0) or 0
            s['avg'] = f"{h/ab:.3f}" if ab > 0 else ".000"
            s['obp'] = f"{(h+bb)/(ab+bb):.3f}" if (ab+bb) > 0 else ".000"
            # SLG = (단타 + 2루타*2 + 3루타*3 + 홈런*4) / 타수
            singles = max(h - doubles - triples - hr, 0)
            tb = singles + doubles*2 + triples*3 + hr*4
            s['slg'] = f"{tb/ab:.3f}" if ab > 0 else ".000"
            obp_f = (h+bb)/(ab+bb) if (ab+bb) > 0 else 0
            slg_f = tb/ab if ab > 0 else 0
            s['ops'] = f"{obp_f+slg_f:.3f}"
            s['doubles'] = doubles
            s['triples'] = triples
            # wOBA / wRC+
            woba = calc_woba(ab, h, doubles, triples, hr, bb, year=int(yr))
            s['woba'] = f"{woba:.3f}"
            s['wrc_plus'] = calc_wrc_plus(woba, year=int(yr))
        return sorted(seasons.values(), key=lambda x: x['year'], reverse=True)

    kbo_pitcher_seasons   = aggregate_by_season_pitcher([dict(r) for r in pitcher_stats])
    kbo_batter_seasons    = aggregate_by_season_batter([dict(r) for r in batter_stats])
    fut_pitcher_seasons   = aggregate_by_season_pitcher([dict(r) for r in futures_pitcher])
    fut_batter_seasons    = aggregate_by_season_batter([dict(r) for r in futures_batter])

    # 기록 없는 시즌도 포함 (모든 KBO 시즌 기준으로 채우기)
    all_years = sorted(set(
        [s['year'] for s in kbo_pitcher_seasons] +
        [s['year'] for s in kbo_batter_seasons] +
        [s['year'] for s in fut_pitcher_seasons] +
        [s['year'] for s in fut_batter_seasons]
    ), reverse=True)

    def fill_empty_seasons(seasons, years, is_pitcher):
        existing = {s['year'] for s in seasons}
        for yr in years:
            if yr not in existing:
                if is_pitcher:
                    seasons.append({'year': yr, 'games': 0, 'wins': 0, 'loses': 0, 'holds': 0,
                                    'saves': 0, 'er': 0, 'so': 0, 'bb': 0, 'h': 0, 'hr': 0,
                                    'ip': '-', 'era': '-', 'whip': '-', 'bavg': '-'})
                else:
                    seasons.append({'year': yr, 'games': 0, 'ab': 0, 'h': 0, 'hr': 0,
                                    'rbi': 0, 'bb': 0, 'so': 0, 'r': 0,
                                    'avg': '-', 'obp': '-', 'slg': '-', 'ops': '-'})
        return sorted(seasons, key=lambda x: x['year'], reverse=True)

    kbo_pitcher_seasons = fill_empty_seasons(kbo_pitcher_seasons, all_years, True)
    kbo_batter_seasons  = fill_empty_seasons(kbo_batter_seasons,  all_years, False)
    fut_pitcher_seasons = fill_empty_seasons(fut_pitcher_seasons, all_years, True)
    fut_batter_seasons  = fill_empty_seasons(fut_batter_seasons,  all_years, False)

    # 시즌별 AI 평가
    try:
        season_ai_reports = conn2.execute(
            "SELECT * FROM ai_reports WHERE player_name=? AND report_type='player_season' ORDER BY created_at DESC",
            (pname,)
        ).fetchall()
        season_ai_reports = [dict(r) for r in season_ai_reports]
    except:
        season_ai_reports = []

    return render_template("player.html",
        name=pname,
        player_info=player_info,
        is_pitcher=is_pitcher,
        batter_stats=[dict(r) for r in batter_stats],
        pitcher_stats=[dict(r) for r in pitcher_stats],
        futures_batter=[dict(r) for r in futures_batter],
        futures_pitcher=[dict(r) for r in futures_pitcher],
        kbo_pitcher_seasons=kbo_pitcher_seasons,
        kbo_batter_seasons=kbo_batter_seasons,
        fut_pitcher_seasons=fut_pitcher_seasons,
        fut_batter_seasons=fut_batter_seasons,
        ai_reports=[dict(r) for r in ai_reports],
        player_season_report=player_season_report,
        season_ai_reports=season_ai_reports,
        current_year=current_year,
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
    from database import get_connection
    conn = get_connection()
    batter = conn.execute("SELECT * FROM batter_stats WHERE name=? ORDER BY game_id DESC", (pname,)).fetchall()
    pitcher = conn.execute("SELECT * FROM pitcher_stats WHERE name=? ORDER BY game_id DESC", (pname,)).fetchall()
    conn.close()
    if not batter and not pitcher:
        abort(404)
    return jsonify({"batter": [dict(r) for r in batter], "pitcher": [dict(r) for r in pitcher]})


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
        from analyzer import analyze_game
        content = analyze_game(game_id)
        return jsonify({"success": True, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/player-season", methods=["POST"])
def api_analyze_player_season():
    try:
        from database import get_connection
        import datetime as dt
        data = request.json
        player_name = data.get("player_name")
        is_pitcher  = data.get("is_pitcher", False)
        year        = data.get("year", "")  # 특정 시즌 지정
        league      = data.get("league", "kbo")  # kbo or futures
        if not player_name:
            return jsonify({"error": "선수명 없음"}), 400

        # 이미 생성된 시즌 분석 확인
        conn = get_connection()
        report_key = f"player_season_{year}_{league}" if year else "player_season"
        existing = conn.execute(
            "SELECT content FROM ai_reports WHERE player_name=? AND report_type=? ORDER BY created_at DESC LIMIT 1",
            (player_name, report_key)
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({"success": True, "content": existing["content"], "cached": True})

        if is_pitcher:
            table = "pitcher_stats" if league == "kbo" else "futures_pitcher_stats"
            join  = "games" if league == "kbo" else "futures_games"
            year_filter = f"AND g.date LIKE '{year}%'" if year else ""
            stats = conn.execute(f"""
                SELECT p.*, g.date FROM {table} p
                JOIN {join} g ON p.game_id = g.game_id
                WHERE p.name = ? {year_filter} ORDER BY g.date DESC
            """, (player_name,)).fetchall()
            stats = [dict(r) for r in stats]
            lines = [f"{s['date'][4:6]}/{s['date'][6:]} {s['ip']}이닝 {s['er']}자책 {s['so']}삼진 ERA {s['era']}" for s in stats]
            stat_summary = "\n".join(lines[:30])
            season_label = f"{year}시즌" if year else "이번 시즌"
            league_label = "KBO" if league == "kbo" else "퓨처스리그"
            prompt = f"""두산 베어스 투수 {player_name}의 {season_label} {league_label} 전체 기록을 분석해주세요.

기록 목록:
{stat_summary}

총 {len(stats)}경기 등판, 자책점 {sum(s['er'] for s in stats)}점, 삼진 {sum(s['so'] for s in stats)}개

3~4문단으로 시즌 전체 흐름 평가, 강점, 약점, 발전 방향을 팬 입장에서 따뜻하게 작성해주세요."""
        else:
            table = "batter_stats" if league == "kbo" else "futures_batter_stats"
            join  = "games" if league == "kbo" else "futures_games"
            year_filter = f"AND g.date LIKE '{year}%'" if year else ""
            stats = conn.execute(f"""
                SELECT b.*, g.date FROM {table} b
                JOIN {join} g ON b.game_id = g.game_id
                WHERE b.name = ? {year_filter} ORDER BY g.date DESC
            """, (player_name,)).fetchall()
            stats = [dict(r) for r in stats]
            total_ab  = sum(s['ab'] for s in stats)
            total_h   = sum(s['h'] for s in stats)
            total_hr  = sum(s['hr'] for s in stats)
            total_rbi = sum(s['rbi'] for s in stats)
            avg = f"{total_h/total_ab:.3f}" if total_ab > 0 else ".000"
            season_label = f"{year}시즌" if year else "이번 시즌"
            league_label = "KBO" if league == "kbo" else "퓨처스리그"
            prompt = f"""두산 베어스 타자 {player_name}의 {season_label} {league_label} 전체 기록을 분석해주세요.

시즌 누적: {total_ab}타수 {total_h}안타 {total_hr}홈런 {total_rbi}타점 타율 {avg}
총 {len(stats)}경기 출장

3~4문단으로 시즌 전체 흐름 평가, 강점, 약점, 발전 방향을 팬 입장에서 따뜻하게 작성해주세요."""

        from analyzer import _call_claude
        result = _call_claude(prompt)

        conn.execute(
            "INSERT INTO ai_reports (game_id, report_type, player_name, content, created_at) VALUES ('season', ?, ?, ?, ?)",
            (report_key, player_name, result, dt.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "content": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/player/<game_id>", methods=["POST"])
def api_analyze_player(game_id):
    try:
        from database import get_connection
        player_name = request.json.get("player_name")
        if not player_name:
            return jsonify({"error": "선수명 없음"}), 400

        conn = get_connection()
        existing = conn.execute(
            "SELECT content FROM ai_reports WHERE game_id=? AND report_type='player' AND player_name=? ORDER BY created_at DESC LIMIT 1",
            (game_id, player_name)
        ).fetchone()
        conn.close()

        if existing:
            return jsonify({"success": True, "content": existing["content"], "player_name": player_name, "cached": True})

        from analyzer import analyze_player
        content = analyze_player(game_id, player_name)
        return jsonify({"success": True, "content": content, "player_name": player_name, "cached": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────
# 에러 페이지
# ──────────────────────────────────────────

@app.route("/ai-reports")
def ai_reports_page():
    """AI 분석 목록 페이지"""
    from database import get_connection
    conn = get_connection()
    try:
        reports = conn.execute("""
            SELECT r.*, g.date, g.home_team, g.away_team, g.result
            FROM ai_reports r
            LEFT JOIN games g ON r.game_id = g.game_id
            ORDER BY r.created_at DESC
        """).fetchall()
    except:
        reports = []
    conn.close()
    return render_template("ai_reports.html", reports=[dict(r) for r in reports])


@app.route("/api/ai-reports")
def api_ai_reports():
    """AI 분석 목록 JSON"""
    from database import get_connection
    conn = get_connection()
    try:
        reports = conn.execute("""
            SELECT r.id, r.game_id, r.report_type, r.player_name, r.content, r.created_at,
                   g.date, g.home_team, g.away_team, g.result
            FROM ai_reports r
            LEFT JOIN games g ON r.game_id = g.game_id
            ORDER BY r.created_at DESC
        """).fetchall()
    except:
        reports = []
    conn.close()
    return jsonify([dict(r) for r in reports])



# ──────────────────────────────────────────
# 모바일 앱 API 엔드포인트
# ──────────────────────────────────────────

@app.route("/api/games/recent")
def api_recent_games():
    from database import get_connection
    limit = request.args.get("limit", 10, type=int)
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
    from database import get_connection
    from datetime import datetime as _dt
    year  = request.args.get("year", str(_dt.now().year))
    month = request.args.get("month", str(_dt.now().month).zfill(2))
    month = month.zfill(2)
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
    try:
        from kbo_crawler import get_next_game
        data = get_next_game()
        return jsonify(data if data else {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/players")
def api_players():
    from database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM players WHERE status='active' ORDER BY team_level, position, CAST(number AS INTEGER)"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/player/<name>")
def api_player_detail(name):
    from database import get_connection
    conn = get_connection()
    try:
        player = conn.execute(
            "SELECT * FROM players WHERE name=? LIMIT 1", (name,)
        ).fetchone()
        batter_stats = conn.execute("""
            SELECT b.*, g.date FROM batter_stats b
            JOIN games g ON b.game_id=g.game_id
            WHERE b.name=? ORDER BY g.date DESC
        """, (name,)).fetchall()
        pitcher_stats = conn.execute("""
            SELECT p.*, g.date FROM pitcher_stats p
            JOIN games g ON p.game_id=g.game_id
            WHERE p.name=? ORDER BY g.date DESC
        """, (name,)).fetchall()
        return jsonify({
            "player":        dict(player) if player else {},
            "batter_stats":  [dict(r) for r in batter_stats],
            "pitcher_stats": [dict(r) for r in pitcher_stats],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/stats/team")
def api_team_stats():
    from database import get_connection
    year = request.args.get("year", str(datetime.now().year))
    conn = get_connection()
    try:
        games = conn.execute(
            "SELECT * FROM games WHERE date LIKE ? ORDER BY date", (f"{year}%",)
        ).fetchall()
        wins  = sum(1 for g in games if dict(g)["result"] == "승")
        loses = sum(1 for g in games if dict(g)["result"] == "패")
        draws = sum(1 for g in games if dict(g)["result"] == "무")
        batters = conn.execute("""
            SELECT SUM(b.ab) ab, SUM(b.h) h, SUM(b.hr) hr, SUM(b.rbi) rbi
            FROM batter_stats b JOIN games g ON b.game_id=g.game_id
            WHERE g.date LIKE ?
        """, (f"{year}%",)).fetchone()
        pitchers = conn.execute("""
            SELECT SUM(p.er) er, SUM(p.so) so
            FROM pitcher_stats p JOIN games g ON p.game_id=g.game_id
            WHERE g.date LIKE ?
        """, (f"{year}%",)).fetchone()
        b = dict(batters) if batters else {}
        p = dict(pitchers) if pitchers else {}
        ab, h = b.get("ab",0) or 0, b.get("h",0) or 0
        total_ip = len(games) * 9
        return jsonify({
            "year":   year,
            "wins":   wins,
            "loses":  loses,
            "draws":  draws,
            "avg":    f"{h/ab:.3f}" if ab > 0 else ".000",
            "hr":     b.get("hr", 0),
            "rbi":    b.get("rbi", 0),
            "era":    f"{(p.get('er',0) or 0)*9/total_ip:.2f}" if total_ip > 0 else "0.00",
            "so_pit": p.get("so", 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()





@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "서버 오류"}), 500


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
