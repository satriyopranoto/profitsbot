"""test_env_loader.py — uji parse .env profitsbot (fix komentar inline 30-Sep-2026).

Cek:
1. Nilai yang SUDAH benar tidak berubah oleh perbaikan (tidak ada regresi).
2. Key yang nilainya diikuti komentar ` # ...` jadi bersih (dulu ikut komentar).
3. Nilai ber-quote tetap utuh (`KEY="a # b"`), `#` tanpa spasi tidak dipotong
   (password aman), dan komentar baris penuh diabaikan.

Jalankan: ./.venv/Scripts/python.exe test_env_loader.py
"""
import os
import sys

sys.path.insert(0, r'C:\Users\satri\code\profitsbot')

FAIL = []


def old_parse(v):
    return v.strip().strip('"').strip("'")


def new_parse(v):
    out, q = [], None
    for i, ch in enumerate(v):
        if ch in "\"'":
            q = None if q == ch else (ch if q is None else q)
        if ch == "#" and q is None and i > 0 and v[i - 1] in " \t":
            break
        out.append(ch)
    return "".join(out).strip().strip('"').strip("'")


def cek(nama, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {nama}: {got!r}" + ("" if ok else f" (harap {want!r})"))
    if not ok:
        FAIL.append(nama)


print("1) contoh kasus")
cek("nilai polos", new_parse("100"), "100")
cek("dgn komentar inline", new_parse("cr               # adx_rsi | cr"), "cr")
cek("angka + komentar", new_parse("14                  # period ADX (Wilder)"), "14")
cek("tanpa komentar (spasi ekor)", new_parse("20000000   "), "20000000")
cek("ber-quote utuh", new_parse('"a # b"'), "a # b")
cek("quote + komentar", new_parse('"a # b" # note'), "a # b")
cek("# tanpa spasi TIDAK dipotong (password)", new_parse("pa#ssword123"), "pa#ssword123")
cek("kutip tunggal", new_parse("'cr'  # mode"), "cr")

print("\n2) .env nyata: bandingkan parser lama vs baru (nilai TIDAK ditampilkan)")
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if not os.path.exists(p):
    print("  (.env tidak ada — skip)")
else:
    berubah, sama, rusak_lama = 0, 0, []
    for line in open(p, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        o, n = old_parse(v), new_parse(v)
        if o == n:
            sama += 1
        else:
            berubah += 1
            if "#" in o:
                rusak_lama.append(k)
    print(f"  nilai identik (tanpa regresi) : {sama}")
    print(f"  nilai jadi bersih (diperbaiki): {berubah}")
    print(f"  dari itu, yang dulunya RUSAK (mengandung '#') : {len(rusak_lama)}")
    if rusak_lama:
        print("   contoh key: " + ", ".join(rusak_lama[:6]) + (" ..." if len(rusak_lama) > 6 else ""))
    # tidak boleh ada key kredensial yang berubah
    kred = [k for k in rusak_lama if any(x in k.upper() for x in ("PASS", "PIN", "USER", "TOKEN", "SECRET"))]
    cek("tidak ada key kredensial yang terpengaruh", kred, [])

print("\n3) import profits_bot dgn .env hasil parse baru")
try:
    import profits_bot as P
    cek("STRATEGY terbaca", P.STRATEGY in ("cr", "adx_rsi"), True)
    cek("ADX_PERIOD integer", isinstance(P.ADX_PERIOD, int), True)
    cek("SCAN_INTERVAL", P.SCAN_INTERVAL, P.SCAN_INTERVAL.strip())
    print(f"   STRATEGY={P.STRATEGY} | SCAN_INTERVAL={P.SCAN_INTERVAL} | ADX_PERIOD={P.ADX_PERIOD} "
          f"| TP_PCT={P.TP_PCT} | ORDER_VALUE={P.ORDER_VALUE:.0f}")
except Exception as e:
    print(f"  [FAIL] import profits_bot: {type(e).__name__}: {e}")
    FAIL.append("import profits_bot")

print()
if FAIL:
    print(f"GAGAL: {len(FAIL)} -> {FAIL}")
    sys.exit(1)
print("SEMUA CEK LULUS (env loader)")
