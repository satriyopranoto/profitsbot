"""indicators.py — indikator teknikal dari data harga (close per-menit).

Data tersedia dari /trade-book/chart/<CODE>/price = harga per menit (close-only,
tanpa high/low). Indikator close-based: SMA, EMA, RSI (Wilder), MACD, Bollinger,
Donchian (approksimasi close). ADX/ATR butuh OHLC asli — TIDAK tersedia per-menit.

Semua fungsi menerima list angka (close) urut waktu & return float/None.
"""


def sma(vals, n):
    """Simple Moving Average — None kalau data < n."""
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def ema(vals, n):
    """Exponential Moving Average (Wilder-style multiplier 2/(n+1))."""
    if len(vals) < n:
        return None
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def ema_series(vals, n):
    """EMA utk SEMUA titik (list sepanjang vals, None di awal)."""
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    out[n - 1] = e
    for i in range(n, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi(vals, n=14):
    """RSI Wilder. Butuh >= n+1 titik (untuk gain/loss pertama)."""
    if len(vals) < n + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    # seed avg Wilder (sma n pertama)
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def macd(vals, fast=12, slow=26, signal=9):
    """MACD line, signal line, histogram (nilai terakhir)."""
    if len(vals) < slow + signal:
        return None
    ef = ema_series(vals, fast)
    es = ema_series(vals, slow)
    macd_line = [ef[i] - es[i] if ef[i] is not None and es[i] is not None else None
                 for i in range(len(vals))]
    valid = [m for m in macd_line if m is not None]
    if len(valid) < signal:
        return None
    sig = ema(valid, signal)
    mlast = valid[-1]
    return {"macd": mlast, "signal": sig, "histogram": mlast - sig}


def bollinger(vals, n=20, k=2.0):
    """Bollinger: (middle, upper, lower)."""
    if len(vals) < n:
        return None
    mid = sma(vals, n)
    sd = (sum((v - mid) ** 2 for v in vals[-n:]) / n) ** 0.5
    return {"middle": mid, "upper": mid + k * sd, "lower": mid - k * sd}


def donchian(vals, n=20):
    """Donchian Channel (approksimasi close-only): high/low dari close terakhir n."""
    if len(vals) < n:
        return None
    window = vals[-n:]
    return {"upper": max(window), "lower": min(window), "middle": (max(window) + min(window)) / 2}


def atr_approx(vals, n=14):
    """ATR approksimasi dari |close[i]-close[i-1]| (tanpa high/low asli)."""
    if len(vals) < n + 1:
        return None
    trs = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def crossover(series_a_last, series_b_last, series_a_prev, series_b_prev):
    """True kalau A baru saja memotong B ke ATAS (golden cross)."""
    if None in (series_a_last, series_b_last, series_a_prev, series_b_prev):
        return False
    return series_a_prev <= series_b_prev and series_a_last > series_b_last


def snapshot(closes):
    """Snapshot indikator utk list close — kembalikan dict ringkas."""
    last = closes[-1] if closes else None
    s = {
        "last": last,
        "sma5": sma(closes, 5),
        "sma20": sma(closes, 20),
        "ema12": ema(closes, 12),
        "ema26": ema(closes, 26),
        "rsi14": rsi(closes, 14),
        "macd": macd(closes),
        "boll": bollinger(closes, 20),
        "donchian20": donchian(closes, 20),
        "atr14": atr_approx(closes, 14),
    }
    # sinyal sederhana
    s["trend"] = "UP" if s["sma5"] and s["sma20"] and s["sma5"] > s["sma20"] else (
        "DOWN" if s["sma5"] and s["sma20"] and s["sma5"] < s["sma20"] else "FLAT")
    s["rsi_state"] = "OVERBOUGHT" if s["rsi14"] and s["rsi14"] > 70 else (
        "OVERSOLD" if s["rsi14"] and s["rsi14"] < 30 else "NEUTRAL")
    return s


if __name__ == "__main__":
    # self-test
    import random
    random.seed(1)
    prices = [1000 + i + random.random() * 10 for i in range(100)]
    s = snapshot(prices)
    for k, v in s.items():
        print(f"  {k}: {v}")
