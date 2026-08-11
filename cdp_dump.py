import json, os, time, urllib.request
import websocket

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=15)
mid = 0

def cmd(method, params=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg.get("result", {})

out = r"C:\Users\satri\code\profitsbot\dump"
os.makedirs(out, exist_ok=True)

# 1) HTML penuh
res = cmd("Runtime.evaluate", {"expression": "document.documentElement.outerHTML",
                               "returnByValue": True})
html = res.get("result", {}).get("value", "")
with open(os.path.join(out, "index_rendered.html"), "w", encoding="utf-8") as f:
    f.write(html)
print(f"HTML: {len(html)} chars -> index_rendered.html")
print("--- isi HTML (head) ---")
print(html[:1500])

# 2) daftar script src + fetch isinya dari dalam halaman (tauri.localhost serve asli)
res = cmd("Runtime.evaluate", {
    "expression": "JSON.stringify([...document.scripts].map(s=>s.src))",
    "returnByValue": True})
srcs = json.loads(res.get("result", {}).get("value", "[]"))
print(f"\nscripts: {len(srcs)}")
for s in srcs:
    print("  >", s)
