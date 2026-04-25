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

app = Flask(__name__)


# ──────────────────────────────────────────
# 페이지 라우터
# ──────────────────────────────────────────

@app.route("/")
def index():
    games = get_recent_games(limit=5)
    from database import get_recent_futures_games
    futures_games = get_recent_futures_games(limit=5)
    return render_template("index.html", games=games, futures_games=futures_games)


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
    conn.close()
    return render_template("players.html",
        players=[dict(p) for p in players],
        updated_at=updated_at["updated_at"][:10] if updated_at else "미업데이트"
    )


@app.route("/games")
def games_all():
    games = get_recent_games(limit=200)
    from database import get_recent_futures_games
    futures_games = get_recent_futures_games(limit=200)
    return render_template("games.html", games=games, futures_games=futures_games)


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
            elif d.get('result') == '홀드': s['holds'] += 1
            elif d.get('result') == '세이브': s['saves'] += 1
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
            er = s['er']; ip_inn = o/3 if o > 0 else 0
            s['era'] = f"{er*9/ip_inn:.2f}" if ip_inn > 0 else "-"
        return sorted(seasons.values(), key=lambda x: x['year'], reverse=True)

    def aggregate_by_season_batter(stats):
        seasons = {}
        for b in stats:
            d = dict(b) if not isinstance(b, dict) else b
            yr = d['date'][:4]
            if yr not in seasons:
                seasons[yr] = {'year': yr, 'games':0, 'ab':0, 'h':0, 'hr':0, 'rbi':0, 'bb':0, 'so':0, 'r':0}
            s = seasons[yr]
            s['games'] += 1
            s['ab']  += d.get('ab', 0)
            s['h']   += d.get('h', 0)
            s['hr']  += d.get('hr', 0)
            s['rbi'] += d.get('rbi', 0)
            s['bb']  += d.get('bb', 0)
            s['so']  += d.get('so', 0)
            s['r']   += d.get('r', 0)
        for s in seasons.values():
            s['avg'] = f"{s['h']/s['ab']:.3f}" if s['ab'] > 0 else ".000"
            s['obp'] = f"{(s['h']+s['bb'])/(s['ab']+s['bb']):.3f}" if (s['ab']+s['bb']) > 0 else ".000"
        return sorted(seasons.values(), key=lambda x: x['year'], reverse=True)

    kbo_pitcher_seasons   = aggregate_by_season_pitcher([dict(r) for r in pitcher_stats])
    kbo_batter_seasons    = aggregate_by_season_batter([dict(r) for r in batter_stats])
    fut_pitcher_seasons   = aggregate_by_season_pitcher([dict(r) for r in futures_pitcher])
    fut_batter_seasons    = aggregate_by_season_batter([dict(r) for r in futures_batter])

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

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "찾을 수 없습니다"}), 404


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
