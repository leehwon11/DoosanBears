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
    games = get_recent_games(limit=3)
    return render_template("index.html", games=games)


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
def player_page(name):
    """선수 시즌 기록 + AI 평가 페이지"""
    stats = get_player_stats(name)
    if not stats:
        abort(404)
    from database import get_connection
    conn = get_connection()
    ai_reports = conn.execute(
        "SELECT * FROM ai_reports WHERE player_name=? AND report_type='player' ORDER BY created_at DESC",
        (name,)
    ).fetchall()
    conn.close()
    return render_template("player.html", name=name, stats=stats, ai_reports=[dict(r) for r in ai_reports])


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


@app.route("/api/analyze/player/<game_id>", methods=["POST"])
def api_analyze_player(game_id):
    """선수 개인 평가 생성"""
    try:
        from flask import request
        from analyzer import analyze_player
        player_name = request.json.get("player_name")
        if not player_name:
            return jsonify({"error": "선수명 없음"}), 400
        content = analyze_player(game_id, player_name)
        return jsonify({"success": True, "content": content, "player_name": player_name})
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

if __name__ == "__main__":
    init_db()
    start_scheduler_thread()

    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") != "production"

    print(f"서버 시작 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
