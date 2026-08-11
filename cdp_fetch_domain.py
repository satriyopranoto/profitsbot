"""cdp_fetch_domain.py — intercept semua request via CDP Fetch domain.

Menangkap request login ASLI app (via ipc.localhost plugin http) — TANPA inject JS.
"""
import json
import urllib.request
import websocket
import time

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=300)
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

cmd("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
print("Fetch.enable OK — semua request ter-intercept")

print("\n>>> USER: logout & login di app Profits sekarang! <<<")
t0 = time.time()
while time.time() - t0 < 240:
    try:
        msg = json.loads(ws.recv())
    except Exception:
        continue
    if msg.get("method") == "Fetch.requestPaused":
        p = msg["params"]
        req = p.get("request", {})
        url = req.get("url", "")
        rid = p.get("requestId")
        post = req.get("postData")
        interesting = "identity/login" in url or "plugin%3Ahttp%7Cfetch" in url
        if interesting:
            print("\n=== REQUEST PAUSED ===")
            print("URL:", url[:150])
            print("METHOD:", req.get("method"))
            hdrs = req.get("headers", {})
            print("HEADERS:", json.dumps(hdrs)[:400])
            if post:
                try:
                    pc = json.loads(post)
                    cc = pc.get("clientConfig", pc)
                    print("CLIENTCONFIG:", json.dumps(cc, indent=1)[:900])
                    if cc.get("data"):
                        try:
                            b = bytes(cc["data"])
                            print("DATA(decoded):", b.decode(errors="replace")[:300])
                        except Exception:
                            pass
                except Exception:
                    print("POST:", post[:400])
        # continue semua request
        cmd("Fetch.continueRequest", {"requestId": rid})
ws.close()
