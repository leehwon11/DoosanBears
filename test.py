import sqlite3
conn = sqlite3.connect('doosan.db')

# 각 경기별로 doosan이 홈인지 확인하고 이닝 레이블 수정
games = conn.execute("SELECT game_id, home_team FROM games").fetchall()

fixed = 0
for game_id, home_team in games:
    is_doosan_home = (home_team == "두산")
    
    # doosan 이닝과 opponent 이닝 가져오기
    doosan_inn = conn.execute(
        "SELECT inning, score FROM inning_scores WHERE game_id=? AND team='doosan' ORDER BY inning",
        (game_id,)
    ).fetchall()
    opp_inn = conn.execute(
        "SELECT inning, score FROM inning_scores WHERE game_id=? AND team='opponent' ORDER BY inning",
        (game_id,)
    ).fetchall()
    
    if not doosan_inn and not opp_inn:
        continue
    
    # 두산이 홈이면 doosan이 말(더 많은 이닝 or 9이닝), opponent가 초
    # 실제 점수랑 이닝 합계 비교해서 맞는지 확인
    doosan_total = sum(s for _, s in doosan_inn)
    opp_total = sum(s for _, s in opp_inn)
    
    game = conn.execute("SELECT home_score, away_score FROM games WHERE game_id=?", (game_id,)).fetchone()
    if not game:
        continue
    
    home_score, away_score = game
    
    if is_doosan_home:
        # 두산 홈: doosan=home_score, opponent=away_score
        if doosan_total != home_score or opp_total != away_score:
            # 반대로 저장됨 - 스왑
            conn.execute("UPDATE inning_scores SET team='tmp' WHERE game_id=? AND team='doosan'", (game_id,))
            conn.execute("UPDATE inning_scores SET team='doosan' WHERE game_id=? AND team='opponent'", (game_id,))
            conn.execute("UPDATE inning_scores SET team='opponent' WHERE game_id=? AND team='tmp'", (game_id,))
            fixed += 1
    else:
        # 두산 원정: doosan=away_score, opponent=home_score
        if doosan_total != away_score or opp_total != home_score:
            conn.execute("UPDATE inning_scores SET team='tmp' WHERE game_id=? AND team='doosan'", (game_id,))
            conn.execute("UPDATE inning_scores SET team='doosan' WHERE game_id=? AND team='opponent'", (game_id,))
            conn.execute("UPDATE inning_scores SET team='opponent' WHERE game_id=? AND team='tmp'", (game_id,))
            fixed += 1

conn.commit()
print(f"수정된 경기: {fixed}개")
conn.close()