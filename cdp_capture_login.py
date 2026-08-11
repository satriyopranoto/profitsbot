"""cdp_capture_login.py — Fetch domain + bersihkan storage -> tangkap request login ASLI.

1. Fetch.enable (intercept semua request)
2. localStorage.clear + sessionStorage.clear + reload -> app paksa ke halaman login
3. User submit login -> POST /identity/login tertangkap (URL, headers, body!)
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

cmd("Fetch.enable", {"patterns": [{"urlPattern": "*ipc.localhost*", "requestStage": "Request"}]})
print("Fetch.enable OK (hanya ipc.localhost)")

# bersihkan storage & reload -> app ke halaman login (session hilang)
r = cmd("Runtime.evaluate", {"expression": "localStorage.clear(); sessionStorage.clear(); location.reload(); 'cleared'", "returnByValue": True})
print("storage cleared + reload:", r.get("result", {}).get("result", {}).get("value"))

print("\n>>> USER: isi username & password, SUBMIT login di app sekarang! <<<")
t0 = time.time()
hits = 0
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
        # TANGKAP: IPC fetch yang body-nya clientConfig (mengandung URL API / login)
        post = req.get("postData") or ""
        if "identity/login" in post or ("plugin%3Ahttp%7Cfetch" in url and "identity" in post):
            hits += 1
            print("\n=== LOGIN IPC REQUEST", hits, "===")
            print("URL:", url[:160])
            print("METHOD:", req.get("method"))
            print("HEADERS:", json.dumps(req.get("headers", {}))[:400])
            print("POSTDATA:", post[:1200])
        cmd("Fetch.continueRequest", {"requestId": rid})
print("\n[done — total API hits:", hits, "]")
ws.close()
