"""cdp_test_login.py — test login via plugin:http (jalur app) dari DALAM WebView2."""
import json
import os
import urllib.request
import websocket
from profits_client import load_env, crypto_js_encrypt, PASS_KEY

load_env()
u = os.environ["PROFITS_USERNAME"]
p = os.environ["PROFITS_PASSWORD"]
enc = crypto_js_encrypt(p, PASS_KEY)

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)

payload = {"username": u, "password": enc}
js = """
(async () => {
  try {
    const bodyObj = %s;
    const bodyBytes = Array.from(new TextEncoder().encode(JSON.stringify(bodyObj)));
    const url = 'https://next-dev.profits.co.id/api/identity/login';
    const headers = [
      ['Content-Type', 'application/json'],
      ['X-HEADER', 't'],
      ['X-APP-VERSION', '1.3.3'],
      ['X-APP-BUILD-REV', '8c9ca94.2026-08-10'],
      ['X-APP-PLATFORM', window.__TAURI_OS_PLUGIN_INTERNALS__.platform],
      ['Authorization', 'Bearer ']
    ];
    const rid = await window.__TAURI_INTERNALS__.invoke('plugin:http|fetch', {
      clientConfig: {method: 'POST', url: url, headers: headers, data: bodyBytes,
                     maxRedirections: 0, connectTimeout: 30000, proxy: null}
    });
    const meta = await window.__TAURI_INTERNALS__.invoke('plugin:http|fetch_send', {rid: rid});
    let body = null;
    if (meta && meta.rid) {
      const raw = await window.__TAURI_INTERNALS__.invoke('plugin:http|fetch_read_body', {rid: meta.rid});
      if (raw && typeof raw === 'object' && raw.length !== undefined)
        body = new TextDecoder().decode(new Uint8Array(raw));
      try { await window.__TAURI_INTERNALS__.invoke('plugin:http|fetch_cancel_body', {rid: meta.rid}); } catch(e) {}
    }
    return {status: meta && meta.status, body: body};
  } catch (e) {
    return {error: String(e)};
  }
})()
""" % json.dumps(payload)

ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": js, "awaitPromise": True, "returnByValue": True}}))
while True:
    msg = json.loads(ws.recv())
    if msg.get("id") == 1:
        r = msg.get("result", {}).get("result", {})
        v = r.get("value")
        if isinstance(v, dict) and v.get("body") and len(v["body"]) > 200:
            v["body"] = v["body"][:200] + "..."
        print("HASIL:", json.dumps(v, indent=1) if v else r)
        break
ws.close()
