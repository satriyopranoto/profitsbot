"""cdp_net.py — capture request API Profits via CDP Network (bandingkan dgn client kita).

Jalankan: python cdp_net.py <durasi_detik>
User login manual di app selama capture -> kita lihat request asli /identity/login.
"""
import json
import sys
import time
import urllib.request
import websocket

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=20)
mid = 0

def cmd(method, params=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg.get("result", {})

cmd("Network.enable")
duration = int(sys.argv[1]) if len(sys.argv) > 1 else 45
t0 = time.time()
print(f"[capture {duration}s] login manual di app sekarang...")
seen = set()
while time.time() - t0 < duration:
    try:
        ws.settimeout(1)
        msg = json.loads(ws.recv())
    except Exception:
        continue
    m = msg.get("method", "")
    p = msg.get("params", {})
    if m == "Network.requestWillBeSent" and "next-dev.profits.co.id" in p.get("request", {}).get("url", ""):
        req = p["request"]
        url = req["url"].replace("https://next-dev.profits.co.id", "")
        key = url + "|" + req.get("method", "")
        if key in seen:
            continue
        seen.add(key)
        hdrs = {k: v for k, v in req.get("headers", {}).items()}
        print(f"\n>>> {req.get('method','?')} {url}")
        print("    headers:", json.dumps(hdrs, indent=None)[:600])
        pd = req.get("postData")
        if pd:
            print("    postData:", pd[:300])
        if "identity/login" in url:
            print("    *** LOGIN CAPTURED ***")
            with open(r"C:\Users\satri\code\profitsbot\dump\login_capture.json", "w") as f:
                json.dump({"headers": hdrs, "postData": pd}, f, indent=2)
            print("    -> tersimpan dump/login_capture.json")
ws.close()
print("\n[done]")
