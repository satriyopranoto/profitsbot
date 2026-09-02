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


def sma_series(vals, n):
    """SMA series — list per bar (None utk bar awal < n)."""
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    s = sum(vals[:n])
    out[n - 1] = s / n
    for i in range(n, len(vals)):
        s += vals[i] - vals[i - n]
        out[i] = s / n
    return out


def adx_sma_pct(adx_series_list, close, sma20_list, window=100, adx_min=25):
    """Statistic bullish ala stocktrade: % bar dengan ADX>adx_min & Close>SMA20.

    Window bar terakhir (default 100, mulai bar 20). Return (pct, commentary, valid)
    — valid = jumlah bar yang benar2 dievaluasi (utk guard data pendek).
    Commentary: >=35 'Uptrend Kuat', >=30 'Medium Uptrend', else 'Sideways'.
    """
    valid = bull = 0
    n = len(close)
    start = max(20, n - window)
    for i in range(start, n):
        d = adx_series_list[i]
        sma20 = sma20_list[i]
        if not d or sma20 is None:
            continue
        valid += 1
        if d["adx"] > adx_min and close[i] > sma20:
            bull += 1
    pct = round(100.0 * bull / valid, 1) if valid else 0.0
    if pct >= 35:
        return pct, f"Uptrend Kuat ({pct:.0f}%)", valid
    if pct >= 30:
        return pct, f"Medium Uptrend ({pct:.0f}%)", valid
    return pct, f"Sideways ({pct:.0f}%)", valid


def donchian(vals, n=20):
    """Donchian Channel (approksimasi close-only): high/low dari close terakhir n."""
    if len(vals) < n:
        return None
    window = vals[-n:]
    return {"upper": max(window), "lower": min(window), "middle": (max(window) + min(window)) / 2}


def donchian_sl_switch(high, low, atr_multiple=2.8, atr_period=10):
    """SL Switch paritas EA DonchianSL / protraderbot donchian_sl / usbot switch_sl_series.

    r[i] = highest(high, ero) ; s[i] = lowest(low, ero) atas bar berakhir di i
    (ero = atr_multiple * atr_period). ac = arah Donchian-breakout TERAKHIR
    (ffill left-to-right): high[i] > r_prev[i] -> 1 ; low[i] < s_prev[i] -> -1.
    sl[i] = s[i] jika ac==1 (regime UP) else r[i] (regime DOWN).

    Di regime DOWN (ac=-1) sl = band ATAS (resistance) -> high<sl mudah ->
    sinyal SHORT/FLIP lebih awal (paritas EA). Flip tetap HANYA kalau rumus short
    penuh terpenuhi (bukan semata regime change). Return list sl (float).
    """
    n = len(high)
    if n == 0:
        return []
    ero = max(int(atr_multiple * atr_period), 5)
    r_curr = [0.0] * n
    s_curr = [0.0] * n
    r_prev = [None] * n
    s_prev = [None] * n
    for i in range(n):
        lo = max(0, i - ero + 1)
        r_curr[i] = max(high[lo:i + 1])
        s_curr[i] = min(low[lo:i + 1])
        if i > 0:
            lo2 = max(0, i - ero)
            r_prev[i] = max(high[lo2:i])
            s_prev[i] = min(low[lo2:i])
    ac = 0
    sl = [0.0] * n
    for i in range(n):
        if i > 0 and r_prev[i] is not None:
            if high[i] > r_prev[i]:
                ac = 1
            elif low[i] < s_prev[i]:
                ac = -1
        sl[i] = s_curr[i] if ac == 1 else r_curr[i]
    return sl


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


def adx_series(high, low, close, n=14):
    """ADX Wilder series — list dict {pdi, mdi, adx} per bar (None utk bar awal).

    Dipakai utk deteksi CROSS: bandingkan bar terakhir vs sebelumnya.
    pdi/mdi dihitung PER BAR (bukan nilai final) — adx = Wilder-smoothed DX.
    """
    out = [None] * len(close)
    if len(close) < 2 * n + 1:
        return out
    up, dn, tr = [], [], []
    for i in range(1, len(close)):
        hm = high[i] - high[i - 1]
        lm = low[i - 1] - low[i]
        up.append(hm if (hm > lm and hm > 0) else 0.0)
        dn.append(lm if (lm > hm and lm > 0) else 0.0)
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]),
                      abs(low[i] - close[i - 1])))
    atr = sum(tr[:n]) / n
    su = sum(up[:n]) / n
    sd = sum(dn[:n]) / n
    pdi_list, mdi_list = [], []
    for i in range(n, len(tr)):
        atr = (atr * (n - 1) + tr[i]) / n
        su = (su * (n - 1) + up[i]) / n
        sd = (sd * (n - 1) + dn[i]) / n
        pdi_list.append(100 * su / atr if atr else 0.0)
        mdi_list.append(100 * sd / atr if atr else 0.0)
    dxs = [100 * abs(a - b) / (a + b) if (a + b) else 0.0
           for a, b in zip(pdi_list, mdi_list)]
    if len(dxs) < n:
        return out
    adx = sum(dxs[:n]) / n
    # pdi_list[j] = bar seri index j + n + 1
    out[n + n] = {"pdi": round(pdi_list[n - 1], 2), "mdi": round(mdi_list[n - 1], 2),
                  "adx": round(adx, 2)}
    for j in range(n, len(dxs)):
        adx = (adx * (n - 1) + dxs[j]) / n
        out[j + n + 1] = {"pdi": round(pdi_list[j], 2), "mdi": round(mdi_list[j], 2),
                          "adx": round(adx, 2)}
    return out


def adx_full(high, low, close, n=14):
    """ADX Wilder lengkap (pdi, mdi, adx) dari OHLC asli.

    Butuh >= 2n bar. +DI/-DI = directional indicators; ADX = smoothed DX.
    """
    if len(close) < 2 * n:
        return None
    up, dn, tr = [], [], []
    for i in range(1, len(close)):
        hm = high[i] - high[i - 1]
        lm = low[i - 1] - low[i]
        up.append(hm if (hm > lm and hm > 0) else 0.0)
        dn.append(lm if (lm > hm and lm > 0) else 0.0)
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]),
                      abs(low[i] - close[i - 1])))
    atr = sum(tr[:n]) / n
    su = sum(up[:n]) / n
    sd = sum(dn[:n]) / n
    dxs = []
    pdi = mdi = 0.0
    for i in range(n, len(tr)):
        atr = (atr * (n - 1) + tr[i]) / n
        su = (su * (n - 1) + up[i]) / n
        sd = (sd * (n - 1) + dn[i]) / n
        pdi = 100 * su / atr if atr else 0.0
        mdi = 100 * sd / atr if atr else 0.0
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0)
    if len(dxs) < n:
        return None
    adx = sum(dxs[:n]) / n
    for dx in dxs[n:]:
        adx = (adx * (n - 1) + dx) / n
    return {"pdi": round(pdi, 2), "mdi": round(mdi, 2), "adx": round(adx, 2)}


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
