"""test_top_aggregate.py — agregasi top-values: JUMLAH buy+sell, filter pakai sum (OFFLINE).

Regresi utk fix 2026-10-05: dulu ambil MAX satu sisi (buy/sell) per kode -> nilai
kekecilan -> watchlist meleset dari protraderbot. Sekarang nilai per saham = JUMLAH
val buy+sell, filter & urutan pakai hasil jumlah. Test pakai angka persis dari log.
"""
import sys

sys.path.insert(0, r"C:\Users\satri\code\profitsbot")
from profits_bot import _aggregate_top_values      # noqa: E402

MIN = 100_000_000_000  # MIN_TOP_VAL (100B, rupiah)

FAIL = []


def cek(nama, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {nama}" + ("" if ok else f" -> {got!r} (harap {want!r})"))
    if not ok:
        FAIL.append(nama)


# Struktur persis API /analytics/broker/v2/top-stocks:
# - PACK muncul sebagai buy (73,1B) di satu item & sell (57,5B) di item lain
#   => MAX satu sisi = 73,1B (< 100B) GAGAL lama; JUMLAH 130,6B LULUS (fix).
# - GOTO buy 103,2B + sell 26,6B = 129,8B LULUS.
# - BBCA buy 32,6B + sell 64,6B = 97,2B (< 100B) GAGAL (jangan lolos utk paritas PMP).
# - TLKM/TINS cuma satu sisi & kecil -> GAGAL.
# - kode non-4-huruf "AB" -> dihitung shg filt_fmt=1.
ITEMS = [
    {"buy": {"code": "PACK", "isBuy": True, "val": 73_095_021_200, "freq": 7548, "avg": 451.787},
     "sell": {"code": "TLKM", "isBuy": False, "val": 41_717_397_000, "freq": 3005, "avg": 2266.82}},
    {"buy": {"code": "GOTO", "isBuy": True, "val": 103_180_163_588, "freq": 6565, "avg": 29.9978},
     "sell": {"code": "PACK", "isBuy": False, "val": 57_542_651_600, "freq": 7234, "avg": 439.672}},
    {"buy": {"code": "TINS", "isBuy": True, "val": 25_485_381_000, "freq": 1382, "avg": 4603.74},
     "sell": {"code": "BBCA", "isBuy": False, "val": 64_567_852_500, "freq": 1920, "avg": 6101.32}},
    {"buy": {"code": "BBCA", "isBuy": True, "val": 32_640_105_100, "freq": 2502, "avg": 6121.88},
     "sell": {"code": "GOTO", "isBuy": False, "val": 26_612_070_400, "freq": 5356, "avg": 29}},
    {"buy": {"code": "AB", "isBuy": True, "val": 500_000_000_000},
     "sell": {"code": "ZZZZ", "isBuy": False, "val": 1}},
]

PACK_TOT = 73_095_021_200 + 57_542_651_600      # 130.637.672.800
GOTO_TOT = 103_180_163_588 + 26_612_070_400     # 129.792.233.988

print("1) agregasi inti (data nyata):")
rows, filt_fmt, filt_val = _aggregate_top_values(ITEMS, MIN)
cek("kode lolos & urut oleh TOTAL desc", [r["code"] for r in rows], ["PACK", "GOTO"])
cek("PACK.val = jumlah buy+sell",
    rows[0]["val"], PACK_TOT)
cek("GOTO.val = jumlah buy+sell",
    rows[1]["val"], GOTO_TOT)
cek("PACK terwakili sisi buy (val terbesar -> isBuy True)",
    rows[0]["isBuy"], True)
cek("GOTO terwakili sisi buy (val terbesar -> isBuy True)",
    rows[1]["isBuy"], True)

print("\n2) eksplisit regresi lama-vs-baru:")
old_max_pack = max(73_095_021_200, 57_542_651_600)   # 73,1B < 100B => OLD GAGAL
cek("OLD: MAX sisi PACK < 100B (bukti bug lama)", old_max_pack < MIN, True)
cek("BARU: JUMLAH PACK >= 100B (PACK lolos)", PACK_TOT >= MIN, True)
cek("BBCA total 97,2B -> TIDAK lolos (paritas PMP tidak dibagai)", "BBCA" in [r["code"] for r in rows], False)

print("\n3) penghitung filter:")
cek("filt_val = kode total<100B (TLKM,TINS,BBCA,ZZZZ=1)", filt_val, 4)
cek("filt_fmt = kode non-[A-Z]{4} (AB)", filt_fmt, 1)
cek("BBB... (ZZZZ = 4 huruf, ikut terhitung)", "ZZZZ" in [r["code"] for r in rows], False)

print("\n4) kosong & semua-di-filter:")
r2, ff2, fv2 = _aggregate_top_values([], MIN)
cek("items kosong -> rows kosong, 0 filter", (r2, ff2, fv2), ([], 0, 0))
r3, ff3, fv3 = _aggregate_top_values(
    [{"buy": {"code": "SRSN", "val": 5_000_000_000},
      "sell": {"code": "KIJA", "val": 4_000_000_000}}], MIN)
cek("semua di-bawah floor -> rows kosong, filt_val=2", (r3, fv3), ([], 2))

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} -> {FAIL}")
    sys.exit(1)
print("SEMUA CEK LULUS (agregasi top-values: JUMLAH buy+sell, filter pakai sum)")