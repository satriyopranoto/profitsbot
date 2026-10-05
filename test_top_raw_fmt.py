"""test_top_raw_fmt.py — formatter RAW top-values dgn pemisah ribuan (OFFLINE).

Uji `_fmt_top_side` pada data persis dari log live (analytics /broker/v2/top-stocks)
& struktur fallback tradebook. Fungsi murni tampilan — data logika tidak tersentuh.
"""
import sys

sys.path.insert(0, r"C:\Users\satri\code\profitsbot")
from profits_bot import _fmt_top_side      # noqa: E402

FAIL = []


def cek(nama, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {nama}" + ("" if ok else f" -> {got!r} (harap {want!r})"))
    if not ok:
        FAIL.append(nama)


def cek_true(nama, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {nama}")
    if not cond:
        FAIL.append(nama)


# persis baris #1 log live: buy GOTO
row = {"code": "GOTO", "isBuy": True, "val": 87368672048, "vol": 2912541294,
       "freq": 4285, "avg": 29.9974, "fval": 0}
want = "{'code': 'GOTO', 'isBuy': True, 'val': 87,368,672,048, 'vol': 2,912,541,294, " \
       "'freq': 4,285, 'avg': 29.9974, 'fval': 0}"

print("1) item analytics (persis log):")
cek("format penuh", _fmt_top_side(row), want)
cek("countbar dihasilkan", "'val': 87,368,672,048" in _fmt_top_side(row), True)
cek("isBuy boolean utuh", "'isBuy': True" in _fmt_top_side(row), True)
cek("fval=0 tetap angka", "'fval': 0" in _fmt_top_side(row), True)

print("\n2) ekor/ganjil:")
cek("None -> {}", _fmt_top_side(None), "{}")
cek("dict kosong -> {}", _fmt_top_side({}), "{}")
cek("val=0", _fmt_top_side({"val": 0}), "{'val': 0}")

print("\n3) fallback tradebook (key: curr/change/lot):")
tb = {"code": "BBCA", "curr": "6100", "change": "5", "val": 29475772500,
      "freq": 915, "lot": 0, "avg": 6102.8971}
s = _fmt_top_side(tb)
print(f"    -> {s}")
cek_true("val ribu (29,475,772,500)", "'val': 29,475,772,500" in s)
cek_true("freq ribu (915)", "'freq': 915" in s)
cek_true("freq 915 TIDAK jadi 0,915", "'freq': 0" not in s)
cek_true("code string ke-quote", "'code': 'BBCA'" in s)
cek_true("avg float g-format", "'avg': 6102.9" in s)

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} -> {FAIL}")
    sys.exit(1)
print("SEMUA CEK LULUS (formatter ribu RAW top-values)")