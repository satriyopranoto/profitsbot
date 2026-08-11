"""cdp_capture_all.py — wrap invoke + fetch + XHR di halaman aktif.

Menangkap request login app apapun jalurnya (plugin http / fetch / XHR).
"""
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
  if (window.__captureAll) return 'already';
  window.__captureAll = [];
  const rec = (kind, url, method, headers, body) => {
    window.__captureAll.push({kind, url: String(url), method, headers, body: body ? String(body).slice(0, 500) : null});
    console.log('CAPTURE ' + kind + ' ' + String(url).slice(0, 120));
  };

  // 1) invoke (plugin http)
  try {
    const inv = window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke;
    if (inv) window.__TAURI_INTERNALS__.invoke = function(cmd2, args, opts) {
      if (cmd2 === 'plugin:http|fetch') {
        try {
          const cc = (args && args.clientConfig) || {};
          let body = cc.data;
          if (body && typeof body === 'object' && body.length !== undefined)
            body = new TextDecoder().decode(new Uint8Array(body));
          rec('invoke', cc.url, cc.method, JSON.stringify(cc.headers), body);
        } catch(e) {}
      }
      return inv.apply(this, arguments);
    };
  } catch(e) {}

  // 2) fetch browser
  try {
    const of = window.fetch;
    if (of) window.fetch = function(input, init) {
      try {
        const url = typeof input === 'string' ? input : (input && input.url);
        const method = (init && init.method) || (input && input.method) || 'GET';
        rec('fetch', url, method, JSON.stringify(init && init.headers), init && init.body);
      } catch(e) {}
      return of.apply(this, arguments);
    };
  } catch(e) {}

  // 3) XHR
  try {
    const oo = XMLHttpRequest.prototype.open;
    const os = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(m, u) { this.__u = u; this.__m = m; return oo.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function(body) {
      try { rec('xhr', this.__u, this.__m, null, body); } catch(e) {}
      return os.apply(this, arguments);
    };
  } catch(e) {}

  return 'capture-all hooked';
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
            if isinstance(v, str) and v.startswith("CAPTURE"):
                print("CAPTURED:", v[:200])

r = cmd("Runtime.evaluate", {"expression": "JSON.stringify(window.__captureAll || [])", "returnByValue": True})
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
