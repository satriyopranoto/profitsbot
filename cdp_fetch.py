import json, os, urllib.request
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

# fetch semua script + stylesheet dari dalam halaman (tauri.localhost serve asli)
expr = """(async () => {
  const urls = new Set([
    ...[...document.scripts].map(s => s.src),
    ...[...document.querySelectorAll('link[rel=stylesheet]')].map(l => l.href)
  ]);
  const res = {};
  for (const u of urls) {
    try {
      const r = await fetch(u);
      const t = await r.text();
      res[u] = t;
    } catch (e) { res[u] = 'FETCH_ERR: ' + e.message; }
  }
  return JSON.stringify(res);
})()"""
res = cmd("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                               "returnByValue": True})
val = res.get("result", {}).get("value", "")
assets = json.loads(val)
for u, t in assets.items():
    fn = os.path.join(out, u.rstrip("/").split("/")[-1] or "index")
    with open(fn, "w", encoding="utf-8") as f:
        f.write(t)
    print(f"{fn}: {len(t)} chars")
