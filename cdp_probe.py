import json
import urllib.request
import websocket

with urllib.request.urlopen("http://localhost:9222/json") as r:
    targets = json.load(r)
page = next(t for t in targets if t.get("type") == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)

def ev(expr, await_p=False):
    ws.send(json.dumps({"id": 99, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "awaitPromise": await_p, "returnByValue": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == 99:
            return msg

print(ev("typeof window.__TAURI_INTERNALS__"))
print(ev("typeof window.__TAURI_INTERNALS__.invoke"))
print(ev("window.__TAURI_OS_PLUGIN_INTERNALS__ ? window.__TAURI_OS_PLUGIN_INTERNALS__.platform : 'n/a'"))
# coba invoke plugin yang pasti ada: event getCurrent
print(ev("(async()=>{ try { const r = await window.__TAURI_INTERNALS__.invoke('plugin:http|fetch', {clientConfig:{method:'GET', url:'https://next-dev.profits.co.id/api/catalog/company/BBCA', headers:[], data:null, maxRedirections:0, connectTimeout:15000, proxy:null}}); return {t: typeof r, v: r, s: JSON.stringify(r).slice(0,300)}; } catch(e) { return {err: String(e)}; } })()", True))
ws.close()
