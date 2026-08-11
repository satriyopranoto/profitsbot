import re, os

path = r"C:\Users\satri\AppData\Local\Profits\profits.exe"
with open(path, "rb") as f:
    data = f.read()

def pr(b):
    return sum(1 for x in b if 9 <= x <= 13 or 32 <= x < 127) / len(b) if b else 0

out = r"C:\Users\satri\code\profits_extract\frontend"
os.makedirs(out, exist_ok=True)

# ambil 4 asset path
targets = [b"/index.html", b"/assets/index-BUMcGDRC.js",
           b"/assets/index-CbZLwW9f.css", b"/assets/about-settings-privacy-CZr6dNmC.js",
           b"/assets/about-settings-disclaimer-DCM6lmi3.js"]
for t in targets:
    idx = data.find(t)
    if idx < 0:
        print(f"{t.decode():40s} TIDAK ADA")
        continue
    # [len u32][data][path\0]: len di idx-4, data = idx-len .. idx
    ln = int.from_bytes(data[idx-4:idx], "little")
    if 0 < ln < 20_000_000:
        blob = data[idx-ln:idx]
        r = pr(blob)
        print(f"{t.decode():40s} len={ln:>9} printable={r:.2f} head={blob[:50]!r}")
        if r > 0.55:
            fn = os.path.join(out, t.decode().lstrip("/").replace("/", "_"))
            with open(fn, "wb") as f:
                f.write(blob)
            print(f"   -> SAVED {fn}")
    else:
        print(f"{t.decode():40s} len invalid={ln}")
