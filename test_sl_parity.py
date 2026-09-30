"""test_sl_parity.py — uji paritas SL profitsbot ↔ CR/protraderbot (fix 2026-09-30).
Jalankan: ./.venv/Scripts/python.exe test_sl_parity.py

Yang diuji:
1. tick_size / next_tick_down = fraksi harga IDX (port protraderbot).
2. sl_donchian_plan (SIZING) pakai level SAMA dengan SL yang dipasang
   (sl_donchian_price = min(low,28)) — dulu beda (min(close,28)-1).
3. Trigger SL selalu kelipatan tick sah (formula lama int(level)-1 sering tidak).
4. install_sl_now: retry sampai sukses; gagal bersih setelah N percobaan.
"""
import sys

sys.path.insert(0, r'C:\Users\satri\code\profitsbot')
import indicators as ind
import profits_bot as pb

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


def bars(low):
    """28 bar; low terendah = `low` (di bar ke-5), sisanya lebih tinggi."""
    out = []
    for i in range(28):
        v = low if i == 5 else low + 10 + i
        out.append({"o": v, "h": v + 2, "l": v, "c": v + 1})
    return out


def bot_uji(low):
    b = pb.ProfitsBot.__new__(pb.ProfitsBot)   # tanpa __init__ (tidak perlu login)
    b.live = False
    b.log = lambda *a, **k: None
    b.fetch_ohlc = lambda code, interval="15m", range_="5d", min_bars=0: bars(low)
    return b


print("1) tick_size / next_tick_down (fraksi harga IDX)")
for px, want in [(70, 1), (199, 1), (200, 2), (499, 2), (500, 5),
                 (1999, 5), (2000, 5), (2005, 10), (4999, 10), (5001, 25)]:
    cek(f"tick_size({px})", ind.tick_size(px), want)
cek("next_tick_down(2000) = 1995 (contoh user)", ind.next_tick_down(2000), 1995)

print("\n2) SIZING vs SL YANG DIPASANG — level harus identik")
for low in (70, 480, 1999, 2000, 2005, 5001):
    b = bot_uji(low)
    plan = b.sl_donchian_plan("TEST", "15m")
    lvl = int(b.sl_donchian_price("TEST", "15m"))
    cek_true(f"low {low}: error kosong", "error" not in plan, str(plan.get("error", "")))
    cek(f"low {low}: plan.lower == level dipasang", plan.get("lower"), lvl)
    # trigger = level (dibulatkan ke tick sah bila perlu) − 1 tick
    aligned = lvl - (lvl % ind.tick_size(lvl)) if lvl % ind.tick_size(lvl) else lvl
    cek(f"low {low}: trigger = level_aligned − 1 tick",
        plan["trigger"], ind.next_tick_down(aligned))

print("\n3) trigger wajib kelipatan tick sah (perbandingan formula lama)")
for low in (33, 1999, 2000, 2005, 5001, 480):
    b = bot_uji(low)
    trig = b.sl_donchian_plan("TEST", "15m")["trigger"]
    lama = max(int(low) - 1, 1)
    cek_true(f"low {low}: trigger {trig} % tick({trig}) == 0",
             trig % ind.tick_size(trig) == 0)
    print(f"        (formula lama = {lama}, % tick = {lama % ind.tick_size(lama)})")

print("\n4) install_sl_now — retry")
b = bot_uji(1000)
pb.SL_RETRY, pb.SL_RETRY_DELAY = 3, 0
n = {"c": 0}


def gagal_2x(code, trig, qty):
    n["c"] += 1
    return {"error": "stock not found"} if n["c"] < 3 else {}


b.set_stop_loss = gagal_2x
cek_true("gagal 2x lalu sukses -> True (3 percobaan)",
         b.install_sl_now("TEST", 995, 1) is True and n["c"] == 3)
n["c"] = 0


def selalu_gagal(code, trig, qty):
    n["c"] += 1
    return {"error": "stock not found"}


b.set_stop_loss = selalu_gagal
cek_true("gagal semua -> False (3 percobaan, tanpa exception)",
         b.install_sl_now("TEST", 995, 1) is False and n["c"] == 3)

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} cek -> {FAIL}")
    sys.exit(1)
print("SEMUA CEK LULUS")
