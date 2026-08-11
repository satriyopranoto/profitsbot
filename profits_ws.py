"""profits_ws.py — subscribe harga real-time dari WS Profits (READ-ONLY).

Protokol (dari RE bundle):
  connect:  wss://stream.profits.co.id?key=<socket-token>
  subscribe: sub|market|<SYMBOL>|<res>
  pesan:    price$<CODE>|<current>|<prev>|<open>|<high>|<low>
            order_book$..., trade$..., status$..., BC$reload
  heartbeat: "ping" tiap 20s
"""
import json
import sys
import time
import websocket


def parse_price(payload):
    """price$CODE|current|prev|open|high|low (pipe-delimited)."""
    e = payload.split("|")
    if len(e) < 6:
        return None
    cur, prev = float(e[1]), float(e[2])
    chg = cur - prev
    chg_p = (chg / prev * 100) if prev else 0.0
    return {"code": e[0], "current": cur, "change": chg, "changeP": round(chg_p, 2),
            "open": float(e[3]), "high": float(e[4]), "low": float(e[5])}


def stream(symbols, key, duration=30):
    url = f"wss://stream.profits.co.id/market?key={key}"
    ws = websocket.create_connection(url, timeout=15)
    print(f"[WS] connected: {url[:60]}...")
    # protokol asli app: sub|<market>|<channel>|<symbols> (channel: price/order_book/trade/status)
    for s in symbols:
        ws.send(f"sub|market|price|{s}")
        print(f"[WS] sub|market|price|{s}")
    last_ping = time.time()
    t0 = time.time()
    while time.time() - t0 < duration:
        try:
            ws.settimeout(10)
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            if time.time() - last_ping > 20:
                ws.send("ping")
                last_ping = time.time()
            continue
        if not msg:
            continue
        if msg == "ping":  # server ping -> balas pong (kalau tidak, koneksi di-drop!)
            ws.send("pong")
            continue
        if msg == "pong":
            continue
        if "|" in msg and "$" not in msg:
            continue  # control/ack
        if "$" in msg:
            chan, payload = msg.split("$", 1)
            if chan == "price":
                p = parse_price(payload)
                if p:
                    print(f"  PRICE {p['code']}: {p['current']} "
                          f"({p['change']:+g} / {p['changeP']:+.2f}%) "
                          f"O:{p['open']} H:{p['high']} L:{p['low']}")
            else:
                print(f"  [{chan}] {payload[:120]}")
    ws.close()
    print("[WS] closed")


if __name__ == "__main__":
    import os
    import profits_client as pc

    pc.load_env()
    u = os.environ.get("PROFITS_USERNAME") or sys.argv[1]
    p = os.environ.get("PROFITS_PASSWORD") or sys.argv[2]
    symbols = sys.argv[3].split(",") if len(sys.argv) > 3 else ["BBCA", "BBRI"]
    dur = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    print("== login ==")
    r = pc.login(u, p)
    if not pc._session:
        print("GAGAL login:", r)
        sys.exit(1)
    print("  OK")
    print("== socket-token ==")
    st = pc.generate_market_token()
    key = st.get("data")
    if not key:
        print("GAGAL token:", st)
        sys.exit(1)
    print("  key OK:", str(key)[:20], "...")
    stream(symbols, key, duration=dur)
