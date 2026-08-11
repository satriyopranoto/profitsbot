import json, urllib.request, os, base64

# 1) daftar target
with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
os.makedirs(r"C:\Users\satri\code\profitsbot\dump", exist_ok=True)
for t in targets:
    print(f"  [{t.get('type')}] {t.get('title','')[:40]:42s} {t.get('url','')[:60]}")
    if t.get("type") == "page":
        with open(r"C:\Users\satri\code\profitsbot\dump\target.json", "w") as f:
            json.dump(t, f, indent=2)
        print("  -> target.json tersimpan, ws:", t.get("webSocketDebuggerUrl", "")[:60])
