"""cdp_auto_login_capture.py — isi form login VIA CDP + capture request login ASLI.

TIDAK butuh user: set input values (native setter + events), klik Login,
app sendiri yang enkripsi password (vA) -> POST /identity/login via IPC tertangkap.
"""
import json
import os
import urllib.request
import websocket
import time
from profits_client import load_env

load_env()
u = os.environ["PROFITS_USERNAME"]
p = os.environ["PROFITS_PASSWORD"]

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120)
ws.settimeout(10)
mid = 0

def cmd(method, params=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg

cmd("Fetch.enable", {"patterns": [{"urlPattern": "*ipc.localhost*", "requestStage": "Request"}]})
print("Fetch.enable OK (ipc only)")

# isi form login
js = """
(() => {
  const setVal = (el, val) => {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const inputs = document.querySelectorAll('input');
  let filled = [];
  for (const inp of inputs) {
    const t = (inp.type || '').toLowerCase();
    if (t === 'password') { setVal(inp, %s); filled.push('pw:' + inp.placeholder); }
    else if (t === 'text' || t === 'email' || t === '') { setVal(inp, %s); filled.push('user:' + inp.placeholder); }
  }
  return JSON.stringify({filled: filled, inputs: inputs.length});
})()
""" % (json.dumps(p), json.dumps(u))
r = cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
print("isi form:", r.get("result", {}).get("result", {}).get("value"))

# klik tombol login
js2 = r"""
(() => {
  const btns = [...document.querySelectorAll('button')];
  const target = btns.find(b => /login/i.test(b.innerText || '')) || btns[btns.length - 1];
  if (!target) return 'no button';
  target.click();
  return 'clicked: ' + (target.innerText || '').slice(0, 40);
})()
"""
r = cmd("Runtime.evaluate", {"expression": js2, "returnByValue": True})
print("klik:", r.get("result", {}).get("result", {}).get("value"))

print("\n>>> menunggu request login... <<<")
t0 = time.time()
hits = 0
while time.time() - t0 < 45:
    try:
        msg = json.loads(ws.recv())
    except Exception:
        continue
    if msg.get("method") == "Fetch.requestPaused":
        p = msg["params"]
        req = p.get("request", {})
        url = req.get("url", "")
        post = req.get("postData") or ""
        if "identity/login" in post:
            hits += 1
            print("\n*** LOGIN REQUEST TERTANGKAP ***")
            print("URL:", url)
            print("METHOD:", req.get("method"))
            print("HEADERS:", json.dumps(req.get("headers", {})))
            print("POSTDATA:", post[:1500])
            try:
                cc = json.loads(post).get("clientConfig", {})
                data = cc.get("data")
                if isinstance(data, list):
                    print("DATA(decoded):", bytes(data).decode(errors="replace")[:400])
                print("API URL:", cc.get("url"))
                print("API HEADERS:", json.dumps(cc.get("headers"))[:800])
            except Exception as e:
                print("parse err:", e)
        cmd("Fetch.continueRequest", {"requestId": p.get("requestId")})
print("\n[done — hits:", hits, "]")
ws.close()
