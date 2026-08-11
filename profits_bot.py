"""profits_bot.py — bot trading Profits (Phintraco Sekuritas) — prototype READ-ONLY.

Mode:
  - default DRY-RUN  : semua order di-log, TIDAK dikirim ke server
  - --live           : kirim order beneran (HATI-HATI!)

Alur (terverifikasi):
  1. login()              -> accessToken (auto-refresh via /identity/refresh)
  2. trade_login(PIN)     -> tradeAccessToken (wajib utk /portfolio/* & order)
  3. harga: REST /catalog/company/<CODE>/price (24/7) + WS live saat market buka
  4. sinyal: strategi sederhana (placeholder — integrasikan strategi di sini)
  5. order: POST /portfolio/order + X-APP-FORM: "ro"

Konfigurasi via .env: PROFITS_USERNAME, PROFITS_PASSWORD, PROFITS_PIN.
"""
import json
import os
import sys
import threading
import time

import profits_client as pc
from profits_ws import parse_price

# ------------------------- konfigurasi -------------------------
SYMBOLS = os.environ.get("PROFITS_SYMBOLS", "BBCA,BBRI,ANTM").split(",")
ORDER_VALUE = float(os.environ.get("PROFITS_ORDER_VALUE", "10000000"))  # cap Rp/order
LOT_SIZE = 100  # 1 lot = 100 lembar
MAINT_WINDOW = (22 * 60, 5)  # 22:00-00:05 WIB (server maintenance)


def now_wib():
    """Waktu lokal diasumsikan WIB (UTC+7)."""
    return time.localtime()


def in_maintenance():
    t = now_wib()
    mins = t.tm_hour * 60 + t.tm_min
    return mins >= MAINT_WINDOW[0] or mins < MAINT_WINDOW[1]


# ------------------------- bot -------------------------
class ProfitsBot:
    def __init__(self, live=False, verbose=True):
        self.live = live
        self.verbose = verbose
        self._ws = None
        self._last_price = {}

    def log(self, *a):
        if self.verbose:
            print("[BOT]", *a, flush=True)

    # ---- auth ----
    def login(self):
        pc.load_env()
        u = os.environ.get("PROFITS_USERNAME")
        p = os.environ.get("PROFITS_PASSWORD")
        r = pc.login(u, p)
        if not pc._session:
            raise RuntimeError(f"login gagal: {r}")
        self.log("login OK — user", (r.get("data") or {}).get("user", {}).get("name", "?"))
        return pc._session

    def ensure_token(self):
        """Refresh kalau accessToken mau expired (accessExpired = detik)."""
        s = pc._session
        if not s:
            self.login()
            s = pc._session
        exp = s.get("accessExpired") or 3600
        if (time.time() - _tok_ts.get("t", 0)) > max(exp - 120, 60):
            self.refresh()
        return pc._session.get("accessToken")

    def refresh(self):
        rt = pc._session.get("refreshToken")
        r = pc._req("POST", "/identity/refresh", {"refreshToken": rt})
        tok = (r.get("data") or {}).get("token") or r.get("data") or r.get("token")
        if tok and tok.get("accessToken"):
            pc._session = tok
            _tok_ts["t"] = time.time()
            self.log("token refreshed")
        else:
            self.log("refresh gagal:", json.dumps(r)[:150])

    def trade_login(self):
        """Login trading dengan PIN -> tradeAccessToken (utk portfolio/order)."""
        pin = os.environ.get("PROFITS_PIN")
        if not pin:
            raise RuntimeError("PROFITS_PIN belum di-set di .env")
        r = pc.trade_login(pin)
        # struktur: data.token atau data — parse fleksibel
        tok = (r.get("data") or {}).get("token") or (r.get("data") if isinstance(r.get("data"), dict) else None)
        if tok and tok.get("accessToken"):
            pc._trade_session = tok
            self.log("trade login OK (PIN)")
        else:
            self.log("trade login GAGAL:", json.dumps(r, ensure_ascii=False)[:200])
        return pc._trade_session

    # ---- data ----
    def get_price(self, code):
        """Harga terakhir via REST (jalan 24/7)."""
        r = pc._req("GET", f"/catalog/company/{code}/price", token=self.ensure_token())
        d = r.get("data") or {}
        if d:
            self._last_price[code] = d
        return d

    def get_balance(self):
        return pc._req("GET", "/portfolio/balance", token=pc._trade_session.get("accessToken") if pc._trade_session else None)

    def get_stocks(self):
        return pc._req("GET", "/portfolio/stock", token=pc._trade_session.get("accessToken") if pc._trade_session else None)

    def get_orders(self):
        return pc._req("GET", "/portfolio/order", token=pc._trade_session.get("accessToken") if pc._trade_session else None)

    # ---- order ----
    def place_order(self, code, qty_lot, is_buy, price=None, order_type="limit", gtc=False, split=0):
        """Place order. DRY-RUN: log saja. --live: kirim beneran.

        ⚠️⚠️ qty = dalam LOT (1 lot = 100 lembar) — TERVERIFIKASI LIVE!
        (qty=1 -> total = price*100; qty=100 = 100 LOT = 30,9jt utk ANTM 3090!)
        JANGAN kirim lembar — sell qty=100 ditolak "insufficient balance".

        ⚠️ CASH ONLY — JANGAN PERNAH leverage/margin! Payload = persis bundle
        desktop (tanpa field leverage — fitur itu khusus app MOBILE). Validasi:
        nilai order (qty_lot*100*price) WAJIB <= cash real (totalCash), bukan
        maxLimit/multiplier (kalau <= maxLimit tapi > cash = LEVERAGE implicit!).

        payload (dari bundle): {qty, gtc, isBuy, split, useLimit, price, code, orderType}
        header X-APP-FORM: "ro" (regular order)
        """
        use_limit = order_type != "market"
        payload = {"qty": qty_lot, "gtc": gtc, "isBuy": is_buy, "split": split,
                   "useLimit": use_limit, "price": price, "code": code,
                   "orderType": order_type,
                   "expire": "day"}  # WAJIB — tanpa expire server tolak 400 ("expire required")
        order_value = (qty_lot * 100 * price) if price else None
        # guard CASH: nilai order (dalam RUPIAH) harus <= cash real (tanpa leverage!)
        if order_value:
            bal = self.get_balance()
            cash = (bal.get("data") or {}).get("cash")
            if cash is not None and order_value > cash:
                self.log(f"[BLOKIR] order {code} {qty_lot}lot = Rp{order_value:,.0f} > cash Rp{cash:,.0f} (cash-only!)")
                return None
        plan = {"symbol": code, "qty_lot": qty_lot, "qty_lbr": qty_lot * 100,
                "isBuy": is_buy, "price": price, "type": order_type,
                "value": order_value, "mode": "CASH"}
        if not self.live:
            self.log("[DRY-RUN] ORDER PLAN:", json.dumps(plan, ensure_ascii=False))
            return plan
        if not pc._trade_session:
            self.trade_login()
        req = pc._req("POST", "/portfolio/order", payload,
                      token=pc._trade_session.get("accessToken"),
                      extra={"X-APP-FORM": "ro"})
        self.log("[LIVE] order:", json.dumps(req, ensure_ascii=False)[:300])
        return req

    # ---- automation (stop loss / take profit / trailing) ----
    def set_stop_loss(self, code, trigger_price, qty, execute_price_mode="LAST_PRICE",
                      custom_execute_price=None, expire_date=None):
        """Set stop loss: POST /automation/stoploss.

        payload (dari bundle): {id, code, triggerPrice, executeQty,
        executePriceMode, customExecutePrice, expireDate}
        executePriceMode: "LAST_PRICE" (TERVERIFIKASI dari SL aktif user) |
                          "market" | "limit" (limit -> customExecutePrice)
        expireDate: ISO; default 90 hari (protokol IDX ≤90 hari)
        """
        import datetime
        if expire_date is None:
            expire_date = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        payload = {"id": "", "code": code, "triggerPrice": trigger_price,
                   "executeQty": qty, "executePriceMode": execute_price_mode,
                   "customExecutePrice": custom_execute_price or 0,
                   "expireDate": expire_date}
        if not self.live:
            self.log("[DRY-RUN] STOP LOSS PLAN:", json.dumps(payload, ensure_ascii=False))
            return payload
        if not pc._trade_session:
            self.trade_login()
        r = pc._req("POST", "/automation/stoploss", payload,
                    token=pc._trade_session.get("accessToken"))
        self.log("[LIVE] stop loss:", json.dumps(r, ensure_ascii=False)[:250])
        return r

    def get_stop_losses(self):
        if not pc._trade_session:
            self.trade_login()
        return pc._req("GET", "/automation/stoploss",
                       token=pc._trade_session.get("accessToken"))

    def cancel_automation(self, auto_id, auto_type="stoploss"):
        """Cancel automation: POST /automation/<type>/<id>/cancel.

        TERVERTIFIKASI: type WAJIB di URL (mis. "stoploss") —
        /automation/<id>/cancel -> 404 NOT_FOUND!
        """
        if not pc._trade_session:
            self.trade_login()
        return pc._req("POST", f"/automation/{auto_type}/{auto_id}/cancel",
                       token=pc._trade_session.get("accessToken"))

    def cancel_order(self, order_id):
        if not pc._trade_session:
            self.trade_login()
        return pc._req("POST", f"/portfolio/order/{order_id}/cancel",
                       token=pc._trade_session.get("accessToken"))

    # ---- WS live ----
    def ws_start(self, symbols, on_price=None, on_msg=None):
        """Thread WS market: sub|market|price|<SYM>; balas ping->pong."""
        def runner():
            key = pc.generate_market_token().get("data")
            if not key:
                self.log("WS: gagal dapat socket token")
                return
            url = f"{pc.SOCKET_URL}/market?key={key}"
            import websocket
            ws = websocket.create_connection(url, timeout=15)
            self._ws = ws
            self.log("WS connected")
            for s in symbols:
                ws.send(f"sub|market|price|{s}")
            while True:
                try:
                    ws.settimeout(10)
                    msg = ws.recv()
                except Exception:
                    break
                if not msg:
                    continue
                if msg == "ping":
                    ws.send("pong")
                    continue
                if msg == "pong":
                    continue
                if "$" in msg:
                    chan, payload = msg.split("$", 1)
                    if chan == "price":
                        p = parse_price(payload)
                        if p:
                            self._last_price[p["code"]] = {"current": p["current"], "prev": p.get("prev")}
                        if on_price:
                            on_price(payload)
                        elif on_msg:
                            on_msg(chan, payload)
                    elif on_msg:
                        on_msg(chan, payload)
            self.log("WS closed")

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        return t

    def ws_stop(self):
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    # ---- siklus ----
    def run_once(self, symbols=None):
        """Satu siklus: harga semua symbol -> log posisi -> log order plan (DRY-RUN)."""
        symbols = symbols or SYMBOLS
        self.ensure_token()
        self.log("--- siklus", time.strftime("%H:%M:%S"), "---")
        for code in symbols:
            d = self.get_price(code)
            if d:
                chg = d.get("change", 0)
                print(f"  {code}: {d.get('current')} ({chg:+g}) O:{d.get('open')} "
                      f"H:{d.get('high')} L:{d.get('low')} P:{d.get('prev')}")
        # contoh sinyal placeholder: beli saat harga < prev*0.99 (downtrend 1%) — GANTI dgn strategi
        for code in symbols:
            d = self._last_price.get(code)
            if not d:
                continue
            cur, prev = d.get("current"), d.get("prev")
            if not cur or not prev:
                continue
            if cur <= prev * 0.99 and not in_maintenance():
                qty_lot = max(int(ORDER_VALUE // (cur * 100)), 1)  # dalam LOT
                self.place_order(code, qty_lot, is_buy=True, price=cur, order_type="limit")
        return True


_tok_ts = {"t": 0}


# ------------------------- main -------------------------
def main():
    live = "--live" in sys.argv
    symbols = None
    for i, a in enumerate(sys.argv):
        if a == "--symbols" and i + 1 < len(sys.argv):
            symbols = sys.argv[i + 1].split(",")
    bot = ProfitsBot(live=live)
    bot.login()
    bot.trade_login()
    if live:
        print("!! LIVE MODE — order akan dikirim beneran !!")
    bot.run_once(symbols)
    if not live:
        print("\n[DRY-RUN] Tidak ada order dikirim. Untuk live: python profits_bot.py --live")


if __name__ == "__main__":
    main()
