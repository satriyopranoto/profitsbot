"""test_sl_tf_default.py — kunci TF default SL = SCAN_INTERVAL (bukan "15m") + tick-alignment.

Regresi insiden 05-Okt-2026: SL PTBA terpasang dari level M15 (3120) padahal TF bot M30
(3020), karena `sl_donchian_price`/`sl_donchian_plan`/`mass_sl_setup.py` ber-default "15m".

Offline: tanpa network (fetch_ohlc di-stub) — hanya memeriksa default & aritmatika tick.
Jalankan: ./.venv/Scripts/python.exe test_sl_tf_default.py
"""
import inspect
import os
import sys

REPO = r"C:\Users\satri\code\profitsbot"
os.chdir(REPO)
sys.path.insert(0, REPO)
import profits_bot as P      # noqa: E402
import indicators as ind     # noqa: E402

FAIL = []


def cek(nama, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {nama}: {got}" + ("" if ok else f" (harap {want})"))
    if not ok:
        FAIL.append(nama)


print(f"SCAN_INTERVAL (TF bot) = {P.SCAN_INTERVAL}")

print("\n1) default `interval` = SCAN_INTERVAL (bukan '15m')")
for fn in ("sl_donchian_price", "sl_donchian_switch", "sl_donchian_plan"):
    sig = inspect.signature(getattr(P.ProfitsBot, fn))
    cek(f"ProfitsBot.{fn}", sig.parameters["interval"].default, P.SCAN_INTERVAL)

print("\n2) interval benar-benar diteruskan ke fetch_ohlc (stub, offline)")
b = P.ProfitsBot()
seen = {}


def fake_fetch(code, interval, range_, min_bars=0):
    seen["interval"] = interval
    return [{"o": 1.0, "h": 2.0, "l": 1.0, "c": 1.0} for _ in range(40)]


b.fetch_ohlc = fake_fetch
lvl = b.sl_donchian_price("TEST")              # tanpa interval -> default
cek("tanpa argumen -> SCAN_INTERVAL", seen["interval"], P.SCAN_INTERVAL)
cek("level = min low (stub 1.0)", lvl, 1.0)
b.sl_donchian_price("TEST", "15m")             # eksplisit tetap dihormati
cek("eksplisit '15m' tetap dihormati", seen["interval"], "15m")

print("\n3) sl_trigger = tick-aligned, tepat 1 tick di bawah level")
cases = [(3130, 3120), (3030, 3020), (4510, 4500), (1095, 1090), (2050, 2040),
         (199, 198), (777, 770)]
# catatan 777: BUKAN kelipatan tick 5 -> dibulatkan ke BAWAH dulu (775) lalu -1 tick = 770
# (dua tick di bawah level asli) — konservatif & disengaja, lihat docstring sl_trigger.
for lvl, want in cases:
    got = b.sl_trigger(lvl)
    cek(f"sl_trigger({lvl}) [tick {ind.tick_size(lvl)}]", got, want)
    if got % ind.tick_size(lvl) != 0:
        FAIL.append(f"tick-align {lvl}")
        print(f"  [FAIL] hasil {got} BUKAN kelipatan tick {ind.tick_size(lvl)}")

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} -> {FAIL}")
    sys.exit(1)
print("SEMUA CEK LULUS (TF default SL = SCAN_INTERVAL + trigger tick-aligned)")
