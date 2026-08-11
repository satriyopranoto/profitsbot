"""cdp_hook_login.py v3 — cari posisi lr.login ASLI di runtime via searchInContent.

Flow: Debugger.enable -> Page.reload (dapat scriptParsed & scriptId bundle)
      -> Debugger.searchInContent("lr.login") -> setBreakpoint di kolom asli
      -> tunggu user login -> evaluateOnCallFrame -> tangkap Q.
"""
import json
import urllib.request
import websocket
import time

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180)
ws.settimeout(30)
mid = 0

def cmd(method, params=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg

cmd("Debugger.enable")
cmd("Page.enable")

# reload & kumpulkan scriptParsed -> dapat scriptId bundle
cmd("Page.reload")
script_id = None
t0 = time.time()
while time.time() - t0 < 20:
    msg = json.loads(ws.recv())
    if msg.get("method") == "Debugger.scriptParsed":
        u = msg["params"].get("url", "")
        if "index-BUMcGDRC" in u or ("assets" in u and u.endswith(".js")):
            script_id = msg["params"]["scriptId"]
            print("scriptId:", script_id, "url:", u)
            break
if not script_id:
    print("ERROR: bundle tidak ketemu setelah reload"); raise SystemExit(1)

# dapatkan source RUNTIME & cari offset lr.login
src = cmd("Debugger.getScriptSource", {"scriptId": script_id})
runtime_src = src.get("result", {}).get("scriptSource", "")
print("runtime source len:", len(runtime_src), "| dump len:", len(open(r"C:\Users\satri\code\profitsbot\dump\index-BUMcGDRC.js", encoding="utf-8", errors="replace").read()))
anchor = "password:Q"
col = runtime_src.find(anchor)
print("offset anchor di runtime:", col)
if col < 0:
    print("ERROR: anchor tidak ada di runtime source"); raise SystemExit(1)

bp = cmd("Debugger.setBreakpoint", {"location": {"scriptId": script_id, "lineNumber": 0, "columnNumber": col}})
print("breakpoint:", json.dumps(bp)[:250])

print("\n>>> USER: login di app Profits sekarang! <<<")
t0 = time.time()
while time.time() - t0 < 150:
    try:
        ws.settimeout(5)
        msg = json.loads(ws.recv())
    except Exception:
        continue
    if msg.get("method") == "Debugger.paused":
        print("\n[BREAKPOINT HIT!]")
        cfs = msg["params"].get("callFrames", [])
        for cf in cfs[:6]:
            cid = cf.get("callFrameId")
            ev = cmd("Debugger.evaluateOnCallFrame", {
                "callFrameId": cid,
                "expression": "typeof Q !== 'undefined' ? JSON.stringify({Q: Q, n: s(n)}) : null",
                "returnByValue": True,
            })
            val = ev.get("result", {}).get("result", {}).get("value")
            if val:
                print("DAPAT Q:", val[:300])
                open(r"C:\Users\satri\code\profitsbot\dump\app_enc.txt", "w").write(val)
                print("-> dump/app_enc.txt")
                cmd("Debugger.resume")
                ws.close()
                raise SystemExit(0)
            print("FRAME", cf.get("functionName"), "(tidak ada Q)")
        cmd("Debugger.resume")
ws.close()
print("[timeout]")
