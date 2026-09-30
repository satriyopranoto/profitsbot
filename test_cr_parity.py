"""test_cr_parity.py — PARITAS strategy_cr.py (profitsbot) vs runner backtest.

Uji WAJIB: array buyit/sellit/sl_sw/hbuy/lsell/roc harus IDENTIK dgn
`dynamicportfolio/run_id_candle_rejection.py` untuk data yang sama.

Jalankan: python test_cr_parity.py
"""
import importlib.util
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r'C:\Users\satri\code\profitsbot')

DYN = r'C:\Users\satri\code\dynamicportfolio'
CACHE = os.path.join(DYN, 'cache_ohlc')
CODES = ["BBCA", "BBRI", "PGAS", "UNTR", "ICBP", "ALII", "PTBA", "ASII",
         "ADRO", "AKRA", "MDKA", "ACES"]

# config disamakan di kedua sisi SEBELUM import (SCORE_ROC hanya memengaruhi `roc`)
os.environ["CR_SCORE_ROC"] = "60"
os.environ["PROFITS_CR_SCORE_ROC"] = "60"

import strategy_cr as S  # noqa: E402


def muat_runner():
    sys.argv = ["run_id_candle_rejection.py", "1d", "id"]
    spec = importlib.util.spec_from_file_location(
        "runner_cr", os.path.join(DYN, "run_id_candle_rejection.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


R = muat_runner()
FAIL = []


def cmp_arr(tag, nama, a, b):
    a = np.asarray(a)
    b = np.asarray(b)
    if a.shape != b.shape:
        FAIL.append(f"{tag}:{nama}(shape {a.shape} vs {b.shape})")
        return False
    if a.dtype == bool:
        ok = bool((a == b).all())
    else:
        ok = bool(np.allclose(a, b, equal_nan=True, rtol=1e-9, atol=1e-9))
    if not ok:
        d = np.where(~np.isclose(a.astype(float), b.astype(float), equal_nan=True))[0]
        FAIL.append(f"{tag}:{nama}(beda di {len(d)} bar, contoh idx {d[:5].tolist()})")
        return False
    return True


def _f(a):
    try:
        v = float(a[-1])
        return None if np.isnan(v) else v
    except Exception:
        return None


print(f"runner config: RSI {R.RSI_PERIOD} buyit>{R.RSI_BUYIT:g} shortit<{R.RSI_SHORTIT:g} "
      f"slswitch {R.SL_SWITCH_PERIOD} NO_LATCH {R.NO_LATCH} SCORE_ROC {R.SCORE_ROC}")
print(f"module config: RSI {S.RSI_PERIOD} buyit>{S.RSI_BUYIT:g} shortit<{S.RSI_SHORTIT:g} "
      f"slswitch {S.SL_SWITCH_PERIOD} NO_LATCH {S.NO_LATCH} SCORE_ROC {S.SCORE_ROC}")
print()
print(f"{'kode':6} {'bar':>6} {'buyit':>7} {'sellit':>7} {'sl_sw':>7} {'hbuy':>6} "
      f"{'lsell':>6} {'roc':>5}  {'snapshot vs runner':>20}")
for kode in CODES:
    p = os.path.join(CACHE, f"id_1d_{kode}.JK.pkl")
    if not os.path.exists(p):
        print(f"{kode:6} (cache tidak ada)")
        continue
    h = pd.read_pickle(p)
    if isinstance(h.columns, pd.MultiIndex):
        h.columns = h.columns.get_level_values(0)
    h.columns = [c.lower() for c in h.columns]
    o = h["open"].values.astype(float)
    hh = h["high"].values.astype(float)
    ll = h["low"].values.astype(float)
    c = h["close"].values.astype(float)

    a = R.calc_candle_indicators(o, hh, ll, c)
    b = S.calc_candle_indicators(o, hh, ll, c)
    res = {
        "buyit": cmp_arr(kode, "buyit", a["buyit"], b["buyit"]),
        "sellit": cmp_arr(kode, "sellit", a["sellit"], b["sellit"]),
        "sl_sw": cmp_arr(kode, "sl_sw", a["sl_sw"], b["sl_sw"]),
        "hbuy": cmp_arr(kode, "hbuy", a["hbuy"], b["hbuy"]),
        "lsell": cmp_arr(kode, "lsell", a["lsell"], b["lsell"]),
        "roc": cmp_arr(kode, "roc", a["roc"], b["roc"]),
    }
    snap = S.snapshot(o, hh, ll, c)
    snap_ok = (snap["buyit"] == bool(a["buyit"][-1]) and snap["shortit"] == bool(a["sellit"][-1])
               and abs((snap["sl_sw"] or 0) - (_f(a["sl_sw"]) or 0)) < 1e-9)
    if not snap_ok:
        FAIL.append(f"{kode}:snapshot")
    row = " ".join(("OK" if res[k] else "BEDA").rjust(7 if k != "hbuy" and k != "lsell" else 6)
                   for k in ("buyit", "sellit", "sl_sw", "hbuy", "lsell", "roc"))
    print(f"{kode:6} {len(c):>6} {row}  {'OK' if snap_ok else 'BEDA':>20}")

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} -> {FAIL}")
    sys.exit(1)
print("PARITAS OK — modul profitsbot identik dengan runner backtest")
