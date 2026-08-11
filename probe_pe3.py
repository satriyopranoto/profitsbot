import re

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

print(f"size={len(data)/1e6:.2f}MB")
keys = [b"tauri", b"webview2", b"webview", b"microsoft.web", b"msedgewebview2",
        b"rustc", b"rust_", b"pyarmor", b"pyinstaller", b"python3", b"python3",
        b"nuitka", b"cargo", b"msvcp", b"vcruntime", b"v8", b"node.js",
        b"flask", b"fastapi", b"aiohttp", b"requests", b"urllib3",
        b"websocket", b"chromium"]
for k in keys:
    n = data.lower().count(k)
    if n:
        print(f"  {k.decode():20s} -> {n} hits")

# cari string versi python di log-style strings
for m in re.finditer(rb"python3[0-9.]*", data):
    print("  python3:", m.group().decode())
    break
# cari tanda PyArmor (runtime pyarmor)
for m in re.finditer(rb"pyarmor", data):
    print("  pyarmor ditemukan di offset", m.start())
    break

# .taubndl offset & isi awal
idx = data.find(b".taubndl")
print("  .taubndl name-string offset:", idx)
# cari 'tauri' strings yang terbaca
for m in list(re.finditer(rb"[ -~]{6,60}", data))[:0]:
    pass
tauri_strs = [m.group().decode("latin1") for m in re.finditer(rb"[ -~]{4,40}", data) if b"tauri" in m.group().lower()]
print("  tauri strings:", tauri_strs[:6])
