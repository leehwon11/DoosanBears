"""
두산 베어스 분석 웹사이트 - Flask 웹서버
=========================================
라우터 구조:
  GET /                    - 메인 (최근 경기 목록)
  GET /game/<game_id>      - 경기 상세 리포트
  GET /player/<name>       - 선수 시즌 기록 + AI 평가
  GET /api/games           - 최근 경기 목록 JSON
  GET /api/game/<game_id>  - 경기 상세 JSON
  GET /api/player/<name>   - 선수 기록 JSON

실행:
  python app.py
"""

import os
import threading
from flask import Flask, render_template, jsonify, abort
from dotenv import load_dotenv

from database import init_db, get_recent_games, get_game_detail, get_player_stats

init_db()  # 서버 시작 시 항상 테이블 생성

load_dotenv()

app = Flask(__name__)


# ──────────────────────────────────────────
# 페이지 라우터 (HTML 반환)
# ──────────────────────────────────────────

@app.route("/")
def index():
    """메인 페이지 — 최근 경기 목록"""
    games = get_recent_games(limit=5)
    return render_template("index.html", games=games)


@app.route("/players")
def players_page():
    """선수 목록 페이지"""
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
    """전체 경기 목록 페이지"""
    games = get_recent_games(limit=200)
    return render_template("games.html", games=games)


@app.route("/game/<game_id>")
def game_report(game_id):
    """경기 상세 리포트 페이지"""
    detail = get_game_detail(game_id)
    if not detail.get("game"):
        abort(404)
    return render_template("game.html", detail=detail)


@app.route("/player/<name>")
def player_page(n):
    """선수 페이지 - 타자/투수 자동 구분"""
    name = n
    from database import get_connection
    conn = get_connection()

    try:
        player_info = conn.execute("SELECT * FROM players WHERE name=? LIMIT 1", (name,)).fetchone()
        player_info = dict(player_info) if player_info else {}
    except:
        player_info = {}

    batter_stats = conn.execute("""
        SELECT b.*, g.date, g.result, g.home_team, g.away_team
        FROM batter_stats b JOIN games g ON b.game_id = g.game_id
        WHERE b.name = ? ORDER BY g.date DESC
    """, (name,)).fetchall()

    pitcher_stats = conn.execute("""
        SELECT p.*, g.date, g.result, g.home_team, g.away_team
        FROM pitcher_stats p JOIN games g ON p.game_id = g.game_id
        WHERE p.name = ? ORDER BY g.date DESC
    """, (name,)).fetchall()

    ai_reports = conn.execute(
        "SELECT * FROM ai_reports WHERE player_name=? AND report_type='player' ORDER BY created_at DESC",
        (name,)
    ).fetchall()
    conn2 = conn
    conn.close()

    if not batter_stats and not pitcher_stats and not player_info:
        abort(404)

    is_pitcher = len(pitcher_stats) > len(batter_stats)

    # 시즌 종합 AI 분석
    try:
        player_season_report = conn2.execute(
            "SELECT * FROM ai_reports WHERE player_name=? AND report_type='player_season' ORDER BY created_at DESC LIMIT 1",
            (name,)
        ).fetchone()
        player_season_report = dict(player_season_report) if player_season_report else None
    except:
        player_season_report = None

    return render_template("player.html",
        name=name, player_info=player_info,
        is_pitcher=is_pitcher,
        batter_stats=[dict(r) for r in batter_stats],
        pitcher_stats=[dict(r) for r in pitcher_stats],
        ai_reports=[dict(r) for r in ai_reports],
        player_season_report=player_season_report,
    )


# ──────────────────────────────────────────
# API 라우터 (JSON 반환 — 프론트엔드 JS용)
# ──────────────────────────────────────────

@app.route("/api/games")
def api_games():
    """최근 경기 목록 JSON"""
    games = get_recent_games(limit=10)
    return jsonify(games)


@app.route("/api/game/<game_id>")
def api_game(game_id):
    """경기 상세 JSON"""
    detail = get_game_detail(game_id)
    if not detail.get("game"):
        abort(404)
    return jsonify(detail)


@app.route("/api/player/<name>")
def api_player(name):
    """선수 기록 JSON"""
    stats = get_player_stats(name)
    if not stats:
        abort(404)
    return jsonify(stats)


# ──────────────────────────────────────────
# 스케줄러 백그라운드 실행
# ──────────────────────────────────────────

def start_scheduler_thread():
    """
    Flask 서버와 스케줄러를 함께 실행합니다.
    Railway에서는 app.py 하나만 실행하면 웹서버 + 스케줄러가 같이 돌아요.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from scheduler import run_crawl_job

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_crawl_job,
        trigger=CronTrigger(
            hour="16,17,18,19,20,21,22,23",
            minute="0,30",
            timezone="Asia/Seoul",
        ),
        id="kbo_crawl",
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.start()
    print("백그라운드 스케줄러 시작")


# ──────────────────────────────────────────
# AI 분석 API
# ──────────────────────────────────────────

@app.route("/api/analyze/<game_id>", methods=["POST"])
def api_analyze(game_id):
    """경기 AI 분석 생성 (버튼 클릭 시 호출)"""
    try:
        from analyzer import analyze_all
        from database import get_game_detail
        detail = get_game_detail(game_id)
        if not detail.get("game"):
            return jsonify({"error": "경기 데이터 없음"}), 404
        analyze_all(game_id)
        # 생성된 리포트 반환
        updated = get_game_detail(game_id)
        reports = updated.get("reports", [])
        return jsonify({"success": True, "reports": reports})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/game/<game_id>", methods=["POST"])
def api_analyze_game(game_id):
    """경기 종합 평가만 생성"""
    try:
        from analyzer import analyze_game
        content = analyze_game(game_id)
        return jsonify({"success": True, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/player-season", methods=["POST"])
def api_analyze_player_season():
    """선수 시즌 종합 AI 분석"""
    try:
        from flask import request
        from database import get_connection
        data = request.json
        player_name = data.get("player_name")
        is_pitcher  = data.get("is_pitcher", False)
        if not player_name:
            return jsonify({"error": "선수명 없음"}), 400

        conn = get_connection()

        if is_pitcher:
            stats = conn.execute("""
                SELECT p.*, g.date FROM pitcher_stats p
                JOIN games g ON p.game_id = g.game_id
                WHERE p.name = ? ORDER BY g.date DESC
            """, (player_name,)).fetchall()
            stats = [dict(r) for r in stats]
            lines = [f"{s['date'][4:6]}/{s['date'][6:]} {s['ip']}이닝 {s['er']}자책 {s['so']}삼진 ERA {s['era']}" for s in stats]
            stat_summary = "\n".join(lines[:30])
            prompt = f"""두산 베어스 투수 {player_name}의 이번 시즌 전체 기록을 분석해주세요.

기록 목록:
{stat_summary}

총 {len(stats)}경기 등판, 자책점 {sum(s['er'] for s in stats)}점, 삼진 {sum(s['so'] for s in stats)}개

3~4문단으로 시즌 전체 흐름 평가, 강점, 약점, 발전 방향을 팬 입장에서 따뜻하게 작성해주세요."""
        else:
            stats = conn.execute("""
                SELECT b.*, g.date FROM batter_stats b
                JOIN games g ON b.game_id = g.game_id
                WHERE b.name = ? ORDER BY g.date DESC
            """, (player_name,)).fetchall()
            stats = [dict(r) for r in stats]
            total_ab  = sum(s['ab'] for s in stats)
            total_h   = sum(s['h'] for s in stats)
            total_hr  = sum(s['hr'] for s in stats)
            total_rbi = sum(s['rbi'] for s in stats)
            avg = f"{total_h/total_ab:.3f}" if total_ab > 0 else ".000"
            prompt = f"""두산 베어스 타자 {player_name}의 이번 시즌 전체 기록을 분석해주세요.

시즌 누적: {total_ab}타수 {total_h}안타 {total_hr}홈런 {total_rbi}타점 타율 {avg}
총 {len(stats)}경기 출장

3~4문단으로 시즌 전체 흐름 평가, 강점, 약점, 발전 방향을 팬 입장에서 따뜻하게 작성해주세요."""

        from analyzer import _call_claude
        result = _call_claude(prompt)

        conn.execute(
            "INSERT INTO ai_reports (game_id, report_type, player_name, content, created_at) VALUES ('season', 'player_season', ?, ?, ?)",
            (player_name, result, __import__('datetime').datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "content": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze/player/<game_id>", methods=["POST"])
def api_analyze_player(game_id):
    """선수 개인 평가 - 저장된 결과 있으면 바로 반환, 없으면 생성"""
    try:
        from flask import request
        from analyzer import analyze_player
        from database import get_connection
        player_name = request.json.get("player_name")
        if not player_name:
            return jsonify({"error": "선수명 없음"}), 400

        # 이미 분석된 결과 있는지 확인
        conn = get_connection()
        existing = conn.execute(
            "SELECT content FROM ai_reports WHERE game_id=? AND report_type='player' AND player_name=? ORDER BY created_at DESC LIMIT 1",
            (game_id, player_name)
        ).fetchone()
        conn.close()

        if existing:
            return jsonify({"success": True, "content": existing["content"], "player_name": player_name, "cached": True})

        # 없으면 새로 생성
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
# 실행
# ──────────────────────────────────────────

# gunicorn/직접 실행 모두 스케줄러 시작
import threading
_scheduler_started = False
_scheduler_lock = threading.Lock()

def ensure_scheduler():
    global _scheduler_started
    with _scheduler_lock:
        if not _scheduler_started:
            start_scheduler_thread()
            _scheduler_started = True

# 앱 컨텍스트에서 스케줄러 시작
with app.app_context():
    ensure_scheduler()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") != "production"
    print(f"서버 시작 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
