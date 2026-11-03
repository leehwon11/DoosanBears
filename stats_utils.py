"""
두산 베어스 분석 웹사이트 - 기록 계산 공통 함수 (app.py, analyzer.py에서 함께 사용)
"""


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
