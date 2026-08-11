"""cdp_capture_invoke.py v3 — wrap invoke LANGSUNG di halaman aktif (tanpa reload)."""
import json
import urllib.request
import websocket
import time

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180)
ws.settimeout(15)
mid = 0

def cmd(method, params=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg

wrap = r"""
(() => {
  if (window.__hookedInvoke) return 'already';
  const inv = window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke;
  if (!inv) return 'no invoke';
  window.__capturedFetch = [];
  window.__hookedInvoke = true;
  window.__TAURI_INTERNALS__.invoke = function(cmd, args, opts) {
    if (cmd === 'plugin:http|fetch') {
      try {
        const cc = (args && args.clientConfig) || {};
        let body = cc.data;
        if (body && typeof body === 'object' && body.length !== undefined)
          body = new TextDecoder().decode(new Uint8Array(body));
        window.__capturedFetch.push({url: cc.url, method: cc.method, headers: cc.headers, body: body});
        console.log('INVOKE_FETCH ' + JSON.stringify({url: cc.url, method: cc.method, body: body}).slice(0, 700));
      } catch(e) { console.log('wrap err ' + e); }
    }
    return inv.apply(this, arguments);
  };
  return 'hooked';
})()
"""
r = cmd("Runtime.evaluate", {"expression": wrap, "returnByValue": True})
print("wrap:", r.get("result", {}).get("result", {}).get("value"))

print("\n>>> USER: logout & login di app Profits sekarang! <<<")
t0 = time.time()
while time.time() - t0 < 150:
    try:
        ws.settimeout(5)
        msg = json.loads(ws.recv())
    except Exception:
        continue
    if msg.get("method") == "Runtime.consoleAPICalled":
        for a in msg["params"].get("args", []):
            v = a.get("value")
            if isinstance(v, str) and v.startswith("INVOKE_FETCH"):
                print("CAPTURED:", v[:700])

r = cmd("Runtime.evaluate", {"expression": "JSON.stringify(window.__capturedFetch || [])", "returnByValue": True})
val = r.get("result", {}).get("result", {}).get("value", "[]")
try:
    arr = json.loads(val)
    print("\n=== CAPTURED", len(arr), "request ===")
    for rec in arr:
        print(json.dumps(rec, indent=1)[:700])
        print("---")
except Exception as e:
    print("raw:", val[:400], e)
ws.close()
