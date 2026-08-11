import re, struct

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

# 1) cari index.html / asset paths di seluruh binary
for pat in [rb"index\.html", rb"/assets/", rb"\.js", rb"\.css", rb"\.svg"]:
    hits = [m.start() for m in re.finditer(pat, data)]
    print(f"{pat.decode():12s} -> {len(hits)} hits")

# 2) printable runs >= 200 (JS/HTML besar)
runs = re.findall(rb"[ -~\t\r\n]{200,}", data)
print(f"\nprintable runs >=200: {len(runs)}")
for s in runs[:5]:
    print("   >", s[:150].decode("latin1", "replace").replace("\n", "\\n"))
    print("   ---")

# 3) gzip magic di seluruh file
gz = [m.start() for m in re.finditer(b"\x1f\x8b\x08", data)]
print(f"\ngzip magic hits: {len(gz)}")

# 4) pola embed tauri: 4-byte length diikuti path string? cari path+null setelah length kecil
idx = data.find(b"index.html")
if idx != -1:
    print(f"\nindex.html di offset {idx} (0x{idx:X})")
    print("  konteks 80 byte sebelumnya:", data[idx-80:idx+40].decode("latin1", "replace"))

# 5) cari 'tauri_assets' atau marker embed
for pat in [b"tauri_assets", b"__asset", b"embed_assets", b"window.__TAURI"]:
    i = data.find(pat)
    print(f"{pat.decode():20s} -> {'offset '+str(i) if i!=-1 else 'tidak ada'}")
