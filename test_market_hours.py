"""test_market_hours.py — gate jam pasar profitsbot (`market_open`).

Regresi insiden 05-Okt-2026: bot lapor `market CLOSED (15:32)` padahal IDX baru tutup
15:50 → default `MARKET_CLOSE` 15:30 bikin bot berhenti scan + berhenti cek exit/TP di
20 menit terakhir sesi. Test ini mengunci: default = 15:50 & batas buka/tutup presisi.

Jalankan: ./.venv/Scripts/python.exe test_market_hours.py
"""
import datetime as dt
import sys

sys.path.insert(0, r"C:\Users\satri\code\profitsbot")
import profits_bot as P      # noqa: E402

WIB = dt.timezone(dt.timedelta(hours=7))
RABU = (2026, 10, 7)         # 07-Okt-2026 = Rabu (hari bursa)
SABTU = (2026, 10, 10)
FAIL = []


def cek(nama, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {nama}: {got}" + ("" if ok else f" (harap {want})"))
    if not ok:
        FAIL.append(nama)


def at(h, m, tanggal=RABU):
    return dt.datetime(*tanggal, h, m, 30, tzinfo=WIB)


print(f"konstanta aktif: MARKET_HOURS={P.MARKET_HOURS} OPEN={P.MARKET_OPEN} CLOSE={P.MARKET_CLOSE}")
cek("default CLOSE = 15:50 (paritas protraderbot)", P.MARKET_CLOSE, "15:50")

P.MARKET_HOURS = True   # paksa mode jam bursa utk uji batas
print("\nbatas jam (Rabu):")
cek("08:59 -> tutup", P.market_open(now=at(8, 59)), False)
cek("09:00 -> buka", P.market_open(now=at(9, 0)), True)
cek("12:00 -> buka", P.market_open(now=at(12, 0)), True)
cek("15:30 -> BUKA (insiden: dulu tutup!)", P.market_open(now=at(15, 30)), True)
cek("15:32 -> BUKA (kasus lapor user)", P.market_open(now=at(15, 32)), True)
cek("15:49 -> buka", P.market_open(now=at(15, 49)), True)
cek("15:50 -> tutup (pre-closing)", P.market_open(now=at(15, 50)), False)
cek("16:10 -> tutup", P.market_open(now=at(16, 10)), False)
print("\nakhir pekan:")
cek("Sabtu 10:00 -> tutup", P.market_open(now=at(10, 0, SABTU)), False)

print("\nMARKET_HOURS=0 (24 jam / testing):")
P.MARKET_HOURS = False
cek("Sabtu 22:00 -> buka (testing)", P.market_open(now=at(22, 0, SABTU)), True)

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} -> {FAIL}")
    sys.exit(1)
print("SEMUA CEK LULUS (jam pasar profitsbot: default 15:50, batas presisi)")
