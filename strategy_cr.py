"""strategy_cr.py — mesin sinyal Candle Rejection (CR) untuk profitsbot.

Fungsi `cross_over`, `cross_under`, `calc_candle_indicators` di file ini **DI-EXTRACT
1:1** dari runner backtest `dynamicportfolio/run_id_candle_rejection.py`
(lihat header masing-masing fungsi). JANGAN mengubah logikanya sendirian — kalau runner
berubah, regenerate file ini (script `gen_strategy_cr.py`) supaya paritas terjaga.
Sumber kebenaran definisi sinyal: Pine `candle_rejection_flip.pine`, EA
`CandleRejection.mq4`, AFL `candle_rejection.afl`.

Dipakai profitsbot saat `PROFITS_STRATEGY=cr`:
- Buyit   = (close > hbuy[1]  or close > hbuy)  and low > sl  and RSI > RSI_BUYIT
- Shortit = (close < lsell[1] or close < lsell) and high < sl and RSI < RSI_SHORTIT
  (di profitsbot: Shortit = pemicu EXIT LONG/FLIP — IDX cash-only tidak bisa short)
- TP & SL TIDAK dihitung di sini: jalur profitsbot yang sudah ada dipakai, karena
  aturannya identik (jual bila `close < switch-SL` & floating > PROFITS_TP_PCT;
  SL dipasang band-bawah tick-aligned).

TF mengikuti `PROFITS_SCAN_INTERVAL` (JANGAN hardcode D1) — semua parameter di sini
dalam satuan BAR, jadi berlaku sama di D1/H1/M30 (data TF kecil tetap terbatas span-nya).

Ranking: skor = -ROC(SCORE_ROC) ("saham paling turun dipilih lebih dulu") — mesin dari
keunggulan early-entry CR (A/B 30-Sep-2026: D1 IDX +1224% vs +275,8% saat skor off).
"""
import os

import numpy as np
import pandas as pd

# ── Parameter (satuan BAR; parity Pine/EA/AFL) ───────────────────────────────
RSI_PERIOD = int(os.environ.get("PROFITS_CR_RSI_PERIOD", "14"))
RSI_BUYIT = float(os.environ.get("PROFITS_CR_RSI_BUYIT", "70"))      # parity in_rsi_buyit
RSI_SHORTIT = float(os.environ.get("PROFITS_CR_RSI_SHORTIT", "30"))  # parity in_rsi_shortit
SL_SWITCH_PERIOD = int(os.environ.get("PROFITS_CR_SL_SWITCH_PERIOD", "28"))  # 2.8 x 10 bar
SCORE_ROC = int(os.environ.get("PROFITS_CR_SCORE_ROC", "60"))        # skor ranking = -ROC(60)
# Paritas runner (25-Sep-2026): NO_LATCH=1 (simplifikasi user di TV) — Buyit/Shortit
# = perbandingan LEVEL mentah, tanpa latch hbuyon/lsellon & tanpa gate momentum.
NO_LATCH = os.environ.get("PROFITS_CR_NO_LATCH", "1") == "1"
USE_SWITCH = True      # gate switch-SL di proxbuy/proxsell (parity semua port)


# ── di bawah ini DI-EXTRACT dari runner (jangan edit manual) ────────────────────
def cross_over(a_n, a_prev, b_n, b_prev):
    """crossover 2-bar arah NAIK, non-strict (parity Pine/EA Sep-2026):
    a[n] > b[n] and a[n-1] <= b[n-1]  (a = close, b = level)"""
    return a_n > b_n and a_prev <= b_prev


def cross_under(a_n, a_prev, b_n, b_prev):
    """crossunder 2-bar arah TURUN, non-strict (parity Pine/EA Sep-2026):
    a[n] < b[n] and a[n-1] >= b[n-1]"""
    return a_n < b_n and a_prev >= b_prev


# ──────────────────────────────────────────────────────────
# Candle rejection indicator engine — 1:1 port dari pine/MQL4
# ──────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────
def calc_candle_indicators(o, h, l, c):
    n = len(c)
    o = np.asarray(o, float); h = np.asarray(h, float)
    l = np.asarray(l, float); c = np.asarray(c, float)
    eps = 0.001
    rng = eps + h - l

    lo3 = pd.Series(l).rolling(3).min().values
    lo7 = pd.Series(l).rolling(7).min().values
    hi3 = pd.Series(h).rolling(3).max().values
    hi7 = pd.Series(h).rolling(7).max().values
    hi2 = pd.Series(h).rolling(2).max().values
    lo2 = pd.Series(l).rolling(2).min().values
    # Switch SL (parity EA/pine/afl): HHV(H,ero) / LLV(L,ero), ero = SL_SWITCH_PERIOD
    hi_ero = pd.Series(h).rolling(SL_SWITCH_PERIOD).max().values
    lo_ero = pd.Series(l).rolling(SL_SWITCH_PERIOD).min().values

    # ROC(SCORE_ROC) utk ranking score (A/B): score = -ROC; ROC paling negatif = duluan.
    roc = np.full(n, np.nan)
    if SCORE_ROC > 0:
        roc[SCORE_ROC:] = (c[SCORE_ROC:] - c[:-SCORE_ROC]) / c[:-SCORE_ROC] * 100.0

    # Wilder RSI(RSI_PERIOD) — parity EA iRSI / pine ta.rsi / AFL RSI(14)
    _d   = pd.Series(c).diff()
    _up  = _d.clip(lower=0); _dn = -_d.clip(upper=0)
    _ru  = _up.ewm(alpha=1.0 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean().values
    _rd  = _dn.ewm(alpha=1.0 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean().values
    rsi  = 100 - 100 / (1 + _ru / np.where(_rd == 0, np.nan, _rd))

    # prev-bar (index i-1)
    o1 = np.roll(o, 1); h1 = np.roll(h, 1); l1 = np.roll(l, 1); c1 = np.roll(c, 1)
    h3 = np.roll(h, 3); l3 = np.roll(l, 3)

    buyit  = np.zeros(n, bool)
    sellit = np.zeros(n, bool)
    cl_out = np.full(n, np.nan); shortcl_out = np.full(n, np.nan)
    hbuy_out = np.full(n, np.nan); lsell_out = np.full(n, np.nan)
    sl_sw_out = np.full(n, np.nan)   # switch-SL line (SellIt exit, parity EA)

    _hbuyon = False; _lsellon = False
    _hbuy = np.nan; _cl = np.nan; _lsell = np.nan; _shortcl = np.nan
    _hbuy2 = np.nan; _lsell2 = np.nan
    _hbuy3 = np.nan; _lsell3 = np.nan   # nilai bar i-3 (cross vs hbuy[2]/lsell[2], parity Pine 22-Sep)
    _mom_buy = False; _mom_sell = False
    _ac = 0   # latch switch (valuewhen ab != 0)

    for i in range(10, n):
        oi, hi, li, ci = o[i], h[i], l[i], c[i]
        o1i, h1i, l1i, c1i = o1[i], h1[i], l1[i], c1[i]
        ri = rng[i]
        if ri <= 0: ri = eps

        pBullEngulf = (o1i > c1i and ci > oi and ci >= o1i and ci >= h1i and c1i >= oi
                       and (ci - oi) / ri > 0.6 and (ci - oi) >= (o1i - c1i))
        pHangingMan = ((hi - li) > 4 * (oi - ci) and (ci - li) / ri > 0.6
                       and (oi - li) / ri > 0.6 and l1i < li)
        pBullDoji   = (oi == ci and abs(hi - ci) < abs(li - ci))
        pBullNd     = (abs(oi - ci) <= (hi - li) * 0.1 and abs(hi - ci) < abs(li - ci))
        pPiercing   = (c1i < o1i and (o1i + c1i) / 2 < ci and oi < ci and oi > c1i
                       and ci >= h1i and ci > o1i and (ci - oi) / ri > 0.6)
        pBullHarami = (o1i > c1i and ci >= oi and ci <= o1i and c1i <= oi and (ci - oi) < (o1i - c1i))
        pHammer     = ((hi - li) > 3 * (oi - ci) and (ci - li) / ri > 0.6
                       and (oi - li) / ri > 0.6 and hi < h1i and ci < c1i)
        pLongWhite  = (ci > oi and (ci - oi) / ri > 0.6)

        pShootStar  = ((hi - li) > 3 * (oi - ci) and (hi - ci) / ri > 0.6
                       and (hi - oi) / ri > 0.6 and li > l1i)
        pBearEngulf = (c1i > o1i and oi > ci and oi >= c1i and o1i >= ci and (oi - ci) > (c1i - o1i))
        pBearDoji   = (oi == ci and abs(hi - ci) > abs(li - ci))
        pDarkCloud  = (c1i > o1i and (c1i + o1i) / 2 > ci and oi > ci and oi > c1i
                       and ci > o1i and (oi - ci) / ri > 0.6)
        pBearHarami = (c1i > o1i and oi > ci and oi <= c1i and o1i <= ci and (oi - ci) < (c1i - o1i))
        pBearNd     = (abs(oi - ci) <= (hi - li) * 0.1 and abs(hi - ci) > abs(li - ci))
        pLongBlack  = (oi > ci and (oi - ci) / ri > 0.6)

        bull = (pBullEngulf or pHangingMan or pBullDoji or pBullNd or pPiercing or pBullHarami or pHammer)
        bear = (pShootStar or pBearEngulf or pBearDoji or pDarkCloud or pBearHarami or pBearNd)

        lo3i, lo7i, hi3i, hi7i = lo3[i], lo7[i], hi3[i], hi7[i]
        if np.isnan(lo3i) or np.isnan(lo7i) or np.isnan(hi3i) or np.isnan(hi7i):
            _hbuy3 = _hbuy2; _lsell3 = _lsell2
            _hbuy2 = _hbuy; _lsell2 = _lsell
            continue

        rsi_i = rsi[i]
        if np.isnan(rsi_i): rsi_i = 50.0   # mark unusable bars as neither side (parity ~ enough guard)
        # --- Switch SL filter (parity EA/pine/afl) ---
        keep_buy = True; keep_sell = True
        if USE_SWITCH and i >= 1:
            r_i = hi_ero[i]; s_i = lo_ero[i]
            if not (np.isnan(r_i) or np.isnan(s_i) or np.isnan(hi_ero[i-1]) or np.isnan(lo_ero[i-1])):
                ab = 1 if hi > hi_ero[i-1] else (-1 if li < lo_ero[i-1] else 0)
                if ab != 0: _ac = ab
                sl_sw = s_i if _ac == 1 else r_i
                sl_sw_out[i] = sl_sw
                keep_buy  = li > sl_sw
                keep_sell = hi < sl_sw
        proxbuy  = ((rsi_i < 50.0 and bull and h3[i] >= h1i and lo3i <= lo7i) or pLongWhite) and keep_buy
        proxsell = ((rsi_i > 50.0 and bear and l1i >= l3[i] and hi3i >= hi7i) or pLongBlack) and keep_sell

        # capture pre-update state (== values at bar i-1 / i-2 / i-3)
        H_s1, H_s2 = _hbuy, _hbuy2
        H_s3 = _hbuy3
        LS_s1, LS_s2 = _lsell, _lsell2
        LS_s3 = _lsell3
        hbon_s1, lson_s1 = _hbuyon, _lsellon

        # --- update hbuyon latch + levels ---
        if proxbuy:
            _hbuyon = True
            _hbuy, _cl = hi2[i], lo7i
            _mom_buy = pLongWhite
        elif _hbuyon and not np.isnan(_cl):
            # parity pine/afl/EA: SL-hit (low<cl) TIDAK mematikan latch; hanya
            # crossover(close, hbuy[1]) ke atas yang melepas hbuyon.
            co_h = (not np.isnan(H_s1) and not np.isnan(H_s2)
                    and cross_over(ci, c1i, H_s1, H_s2))         # crossover(close, hbuy[1]) — matikan latch
            if co_h:
                _hbuyon = False

        # --- update lsellon latch + levels ---
        if proxsell:
            _lsellon = True
            _lsell, _shortcl = lo2[i], hi7i
            _mom_sell = pLongBlack
        elif _lsellon and not np.isnan(_shortcl):
            # parity pine/afl/EA: SL-hit (high>shortcl) TIDAK mematikan latch.
            cu_l = (not np.isnan(LS_s1) and not np.isnan(LS_s2)
                    and cross_under(ci, c1i, LS_s1, LS_s2))       # crossunder(close, lsell[1]) — matikan latch
            if cu_l:
                _lsellon = False

        # --- entry signals (parity Pine/EA/AFL 25-Sep-2026) ---
        # Trigger = PERBANDINGAN LEVEL mentah (cross 3-level 22-Sep DIPENSIUNKAN):
        #   Buyit   = (close > hbuy[1]  or close > hbuy)  and low>sl  and RSI > RSI_BUYIT
        #   Shortit = (close < lsell[1] or close < lsell) and high<sl and RSI < RSI_SHORTIT
        # Sinyal = KONDISI state (bisa True beruntun di banyak bar), bukan event 1-bar;
        # anti-duplikat dari gate posisi (MAX_POS) + gate switch-SL. NaN hbuy/lsell
        # (belum ada proxbuy/proxsell) otomatis bikin perbandingan False — parity Pine.
        lvl_buy  = ((ci > H_s1) or (ci > _hbuy)) and (rsi_i > RSI_BUYIT)
        lvl_sell = ((ci < LS_s1) or (ci < _lsell)) and (rsi_i < RSI_SHORTIT)

        if NO_LATCH:
            # User simplification (Sep-2026): no hbuyon/lsellon latch, no momentum gate.
            # Gate switch-SL (17-Sep-2026, parity Pine/AFL/EA): buyit butuh low>sl,
            # shortit butuh high<sl. keep_buy/keep_sell = gate switch (True bila OFF/nan).
            buyit[i]  = lvl_buy and keep_buy
            sellit[i] = lvl_sell and keep_sell
        else:
            # baseline A/B LAMA (CR_NO_LATCH=0): trigger sama, di-gate latch + momentum
            buyit[i]  = ((lvl_buy and hbon_s1) or ((ci > _hbuy) and _mom_buy)) and keep_buy
            sellit[i] = ((lvl_sell and lson_s1) or ((ci < _lsell) and _mom_sell)) and keep_sell

        # roll s+2/s+3 registers
        _hbuy3, _lsell3 = H_s2, LS_s2
        _hbuy2, _lsell2 = H_s1, LS_s1

        hbuy_out[i] = _hbuy; cl_out[i] = _cl
        lsell_out[i] = _lsell; shortcl_out[i] = _shortcl

    return {'buyit': buyit, 'sellit': sellit, 'cl': cl_out, 'shortcl': shortcl_out,
            'hbuy': hbuy_out, 'lsell': lsell_out, 'sl_sw': sl_sw_out, 'roc': roc}


def _rsi_display(c):
    """RSI Wilder (14) — HANYA utk log/laporan.

    Gate RSI yang *berlaku* ada DI DALAM calc_candle_indicators (RSI_BUYIT/
    RSI_SHORTIT), jadi nilai ini tidak boleh dipakai utk keputusan.
    """
    d = pd.Series(np.asarray(c, float)).diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1.0 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean().values
    rd = dn.ewm(alpha=1.0 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean().values
    r = 100 - 100 / (1 + ru / np.where(rd == 0, np.nan, rd))
    return r


def snapshot(o, h, l, c):
    """State sinyal CR di BAR TERAKHIR + level utk log & ranking.

    Return dict:
      buyit/shortit : bool (sudah termasuk gate RSI + gate switch-SL)
      sl_sw         : switch-SL bar terakhir (= band-bawah saat regime UP)
      hbuy/lsell    : level trigger aktif (NaN kalau belum ada proxbuy/proxsell)
      rsi           : RSI utk log (lihat _rsi_display)
      score         : -ROC(SCORE_ROC) utk ranking (None kalau data kurang)
      n             : jumlah bar yang dipakai
    """
    c = np.asarray(c, float)
    ind = calc_candle_indicators(o, h, l, c)

    def _f(a):
        try:
            v = float(a[-1])
            return None if np.isnan(v) else v
        except Exception:
            return None

    rsi = _rsi_display(c)
    score = None
    if SCORE_ROC > 0 and len(c) > SCORE_ROC and c[-1 - SCORE_ROC]:
        score = -(c[-1] - c[-1 - SCORE_ROC]) / c[-1 - SCORE_ROC] * 100.0
    return {
        "buyit": bool(ind["buyit"][-1]),
        "shortit": bool(ind["sellit"][-1]),
        "sl_sw": _f(ind["sl_sw"]),
        "hbuy": _f(ind["hbuy"]),
        "lsell": _f(ind["lsell"]),
        "rsi": _f(rsi),
        "score": score,
        "n": int(len(c)),
    }
