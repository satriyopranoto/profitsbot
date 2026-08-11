import re, os

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

out = r"C:\Users\satri\code\profits_extract\frontend"
os.makedirs(out, exist_ok=True)

# 1) index.html — dari DOCTYPE pertama ke </html> (mentah)
i0 = data.find(b"<!DOCTYPE")
i1 = data.find(b"</html>", i0)
print(f"DOCTYPE@0x{i0:X} -> </html>@0x{i1:X}  len={i1+7-i0}")
html = data[i0:i1+7]
with open(os.path.join(out, "index.html"), "wb") as f:
    f.write(html)
print("--- index.html (potongan) ---")
print(html[:600].decode("utf-8", "replace"))

# 2) cari semua asset path & coba extract dgn pola [len][data][path\0]
#    anchor: path string; data = [len u32] SEBELUM path, len bytes sebelum path
paths = sorted(set(p.decode("latin1") for p in re.findall(
    rb"/assets/[A-Za-z0-9_.-]+\.(?:js|css)", data)))
print(f"\nassets ditemukan: {len(paths)}")
for p in paths:
    idx = data.find(p.encode())
    # pola [len(4) LE][data...][path\0] -> len di idx-4
    if idx >= 4:
        ln = int.from_bytes(data[idx-4:idx], "little")
        blob_start = idx - ln
        if blob_start >= 0 and 0 < ln < 5_000_000:
            blob = data[blob_start:idx]
            # sanity: blob harus printable-ish (text)
            printable = sum(1 for b in blob if 9 <= b <= 13 or 32 <= b < 127) / len(blob)
            if printable > 0.6:
                fname = os.path.join(out, p.split("/")[-1])
                with open(fname, "wb") as f:
                    f.write(blob)
                print(f"  OK  {p}  len={ln} printable={printable:.2f}")
                continue
    print(f"  ??  {p}  (gagal, cek manual)")
