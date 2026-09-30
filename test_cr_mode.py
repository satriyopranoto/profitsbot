"""test_cr_mode.py — uji mode CR profitsbot OFFLINE (tanpa API/kredensial).

Cek:
1. Default STRATEGY = 'adx_rsi' (perilaku lama tidak berubah).
2. `cr_signal()` = array runner (action BUY/SHORT/HOLD harus sama dgn
   run_id_candle_rejection.calc_candle_indicators di bar terakhir).
3. `scan_signals()` mode CR: urutan hasil = skor -ROC menurun ('fallen' = paling
   turun dulu) dan TIDAK memakai statistik uptrend.
4. Data kurang (< CR_MIN_BARS) -> HOLD dgn alasan jelas (bukan crash).

Jalankan: ./.venv/Scripts/python.exe test_cr_mode.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, r'C:\Users\satri\code\profitsbot')
import profits_bot as P            # noqa: E402
import strategy_cr as cr           # noqa: E402

CACHE = r'C:\Users\satri\code\dynamicportfolio\cache_ohlc'
CODES = ["BBCA", "BBRI", "PGAS", "PACK", "MDKA"]
FAIL = []


def cek(nama, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {nama}: {got}" + ("" if ok else f" (harap {want})"))
    if not ok:
        FAIL.append(nama)


def cek_true(nama, cond, info=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {nama} {info}".rstrip())
    if not cond:
        FAIL.append(nama)


def bar_list(kode):
    p = os.path.join(CACHE, f"id_1d_{kode}.JK.pkl")
    if not os.path.exists(p):
        return None
    h = pd.read_pickle(p)
    if isinstance(h.columns, pd.MultiIndex):
        h.columns = h.columns.get_level_values(0)
    h.columns = [c.lower() for c in h.columns]
    return [{"t": int(i.timestamp()) if hasattr(i, "timestamp") else k,
             "o": float(r["open"]), "h": float(r["high"]),
             "l": float(r["low"]), "c": float(r["close"]), "v": 0.0}
            for k, (i, r) in enumerate(h.iterrows())]


def bot(kode):
    b = P.ProfitsBot.__new__(P.ProfitsBot)
    b.live = False
    b.log = lambda *a, **k: None
    b.fetch_ohlc = lambda code, interval="15m", range_="5d", min_bars=0: bar_list(code) or []
    return b


print("1) default strategi")
cek("STRATEGY default", P.STRATEGY, "adx_rsi")
cek("CR rank default", P.CR_SCORE_ORDER, "fallen")

print("\n2) cr_signal == runner (bar terakhir)")
for kode in CODES:
    bl = bar_list(kode)
    if not bl:
        print(f"  ({kode}: cache tidak ada, skip)")
        continue
    o = [x["o"] for x in bl]; h = [x["h"] for x in bl]
    l = [x["l"] for x in bl]; c = [x["c"] for x in bl]
    ind = cr.calc_candle_indicators(o, h, l, c)
    harap = "BUY" if ind["buyit"][-1] else ("SHORT" if ind["sellit"][-1] else "HOLD")
    sig = bot(kode).cr_signal(kode, "1d")
    cek(f"{kode}: action", sig["action"], harap)
    cek_true(f"{kode}: ind['sl'] == runner sl_sw[-1]",
             abs((sig["ind"]["sl"] or 0) - float(ind["sl_sw"][-1])) < 1e-6)

print("\n3) scan_signals mode CR — urutan skor 'fallen' (paling turun dulu)")
try:
    b = bot("BBCA")
    b.top_values = lambda n=15: [{"code": k, "val": (9 - i) * 1e9}
                                 for i, k in enumerate(CODES)]
    P.STRATEGY = "cr"
    res = b.scan_signals(interval="1d")
    skor = [(r["code"], (r.get("ind") or {}).get("cr_score")) for r in res]
    print("   urutan hasil: " + ", ".join(
        f"{k}[{next((x['action'] for x in res if x['code'] == k), '?')}]"
        f":{'n/a' if s is None else format(s, '+.1f')}" for k, s in skor))
    grup = {}
    for r in res:
        grup.setdefault(r["action"], []).append((r.get("ind") or {}).get("cr_score") or -1e9)
    cek_true("skor menurun (fallen dulu) di tiap grup action",
             all(all(a >= bx for a, bx in zip(v, v[1:])) for v in grup.values()),
             f"{ {k: [round(x, 1) for x in v] for k, v in grup.items()} }")
    cek_true("tidak ada gate uptrend dipakai (adx_sma_pct=0)",
             all((r.get("ind") or {}).get("adx_sma_pct") == 0.0 for r in res if r.get("ind")))
finally:
    P.STRATEGY = "adx_rsi"

print("\n4) data kurang -> HOLD, bukan crash")
b = bot("BBCA")
b.fetch_ohlc = lambda code, interval="15m", range_="5d", min_bars=0: bar_list("BBCA")[:40]
sig = b.cr_signal("BBCA", "1d")
cek("action saat data kurang", sig["action"], "HOLD")
cek_true("ada alasan 'data kurang'", "data kurang" in (sig.get("reasons") or [""])[0],
         str(sig.get("reasons")))

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} -> {FAIL}")
    sys.exit(1)
print("SEMUA CEK LULUS (mode CR)")
