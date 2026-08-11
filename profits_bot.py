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
import indicators as ind

# ------------------------- konfigurasi -------------------------
SYMBOLS = os.environ.get("PROFITS_SYMBOLS", "BBCA,BBRI,ANTM").split(",")
PROTRADER_API = os.environ.get("PROTRADER_API", "http://127.0.0.1:8777")  # bot protrader (real-time PMP)
ORDER_VALUE = float(os.environ.get("PROFITS_ORDER_VALUE", "10000000"))  # cap Rp/order
CYCLE_MINUTES = float(os.environ.get("PROFITS_CYCLE_MINUTES", "3"))  # loop scan (menit)
SCAN_INTERVAL = os.environ.get("PROFITS_SCAN_INTERVAL", "15m")  # timeframe sinyal (Yahoo)
AUTO_EXECUTE = os.environ.get("PROFITS_AUTO_EXECUTE", "0") == "1"  # eksekusi otomatis (DRY-RUN)
MARKET_OPEN = os.environ.get("PROFITS_MARKET_OPEN", "09:00")  # jam pasar WIB
MARKET_CLOSE = os.environ.get("PROFITS_MARKET_CLOSE", "15:30")
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

    # ---- data pasar ----
    def top_values(self, n=15):
        """Top values: /trade-book/trade-book/top-stocks — sort by nilai (val).

        Format: [{buy: {code, curr, change, val, freq, lot, avg}, sell: {...}}]
        Ambil item teratas dari sisi buy (val terbesar).
        """
        r = pc._req("GET", "/trade-book/trade-book/top-stocks", token=self.ensure_token())
        items = r.get("data") or []
        rows = []
        for it in items:
            b = it.get("buy") or {}
            rows.append((b.get("val") or 0, b))
        rows.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in rows[:n]]

    def intraday_history(self, code):
        """Harga intraday per menit (sesi terakhir, ~335 titik).

        /trade-book/chart/<CODE>/price?cursor=<ts> -> [{time, price}, ...]
        Bisa dipakai utk indikator intraday (MA/RSI/ADX dari close 1-menit).
        """
        import time as _t
        path = f"/trade-book/chart/{code}/price?cursor={int(_t.time())}"
        r = pc._req("GET", path, token=self.ensure_token())
        return (r.get("data") or []) if isinstance(r, dict) else r

    def flat_positions(self):
        """Flat (floating P/L) per posisi + total.

        /portfolio/stock -> [{code, available, total, avgPrice, price, company}]
        flat = (current - avgPrice) * total
        """
        if not pc._trade_session:
            self.trade_login()
        r = pc._req("GET", "/portfolio/stock",
                    token=pc._trade_session.get("accessToken"))
        rows = []
        tot = 0.0
        for x in (r.get("data") or []):
            cur = x.get("price") or 0
            avg = x.get("avgPrice") or 0
            qty = x.get("total") or 0
            flat = (cur - avg) * qty
            tot += flat
            rows.append({"code": x["code"], "qty": qty, "avg": avg,
                         "current": cur, "flat": round(flat)})
        rows.sort(key=lambda z: z["flat"])
        return {"rows": rows, "total_flat": round(tot)}
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
    def fetch_ohlc(self, code, interval="15m", range_="5d"):
        """OHLC asli dari Yahoo Finance (suffix .JK) — interval 1m/5m/15m/1d.

        Yahoo = sumber OHLC asli (chart Profits delay & API-nya cuma close
        per-menit). Range: 1d (1m) / 5d (5m,15m) / 3mo-1y (1d).
        Return list dict {t: epoch, o,h,l,c, v} urut waktu.
        """
        import urllib.request, urllib.error, time as _t
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.JK"
               f"?range={range_}&interval={interval}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                r = json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}
        res = (r.get("chart", {}).get("result") or [])
        if not res:
            return {"error": "kosong"}
        ts = res[0].get("timestamp") or []
        q = (res[0].get("indicators", {}).get("quote") or [{}])[0]
        rows = []
        for i in range(len(ts)):
            if q["close"][i] is None:
                continue
            rows.append({"t": ts[i], "o": q["open"][i], "h": q["high"][i],
                         "l": q["low"][i], "c": q["close"][i], "v": q["volume"][i]})
        return rows

    def real_time_price(self, code, timeout=8):
        """Harga real-time multi-source (fallback chain):

        1. Bot protrader API lokal (http://127.0.0.1:8777/price/<CODE>) — real-time PMP
           (timeout 8s — pmp_ask di server butuh ~5-6s utk ambil data)
        2. Yahoo Finance .JK (delay ~10 menit) — kalau bot protrader mati
        Return {source, bid, ask, last, vol, ts} / {source, error}.
        """
        import urllib.request, urllib.error, time as _t
        # 1) bot protrader (real-time)
        url = f"{PROTRADER_API}/price/{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "profitsbot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                d = json.loads(resp.read().decode())
            if d.get("last") or d.get("bid") or d.get("ask"):
                d["source"] = "protrader"
                return d
        except Exception:
            pass
        # 2) fallback Yahoo (delay)
        ohlc = self.fetch_ohlc(code, "15m", "5d")
        if isinstance(ohlc, list) and ohlc:
            last = ohlc[-1]
            return {"source": "yahoo", "bid": None, "ask": None,
                    "last": last["c"], "vol": last["v"], "ts": last["t"]}
        return {"source": "none", "error": "semua sumber gagal"}

    def indicator_snapshot(self, code):
        """Ambil intraday history -> hitung semua indikator (MA/RSI/MACD/Boll/DC)."""
        h = self.intraday_history(code)
        if not h:
            return {"code": code, "error": "tidak ada data"}
        closes = [x["price"] for x in h]
        s = ind.snapshot(closes)
        s["code"] = code
        s["points"] = len(closes)
        s["time_first"] = h[0].get("time")
        s["time_last"] = h[-1].get("time")
        return s

    def signal(self, code, interval="15m", range_="5d", adx_n=14):
        """Analisis sinyal utk 1 saham (OHLC Yahoo).

        BUY : +DI cross ABOVE -DI (golden cross) & ADX>=15  — ATAU  +DI>-DI & ADX>=25
        SELL: -DI cross ABOVE +DI (death cross) & ADX>=15  — ATAU  -DI>+DI & ADX>=25
        Filter: RSI wajar + harga vs SMA20 (buy: close>SMA20 utk konfirmasi tren).
        Return {code, action, score, reasons[], ind{...}}.
        """
        ohlc = self.fetch_ohlc(code, interval, range_)
        if isinstance(ohlc, dict):
            return {"code": code, "action": "HOLD", "score": 0,
                    "reasons": [f"data gagal: {ohlc.get('error')}"]}
        if len(ohlc) < 2 * adx_n + 1:
            return {"code": code, "action": "HOLD", "score": 0,
                    "reasons": [f"data kurang ({len(ohlc)} titik)"]}
        high = [x["h"] for x in ohlc]
        low = [x["l"] for x in ohlc]
        close = [x["c"] for x in ohlc]
        s = ind.adx_series(high, low, close, adx_n)
        last = s[-1]
        prev = s[-2]
        if not last or not prev:
            return {"code": code, "action": "HOLD", "score": 0,
                    "reasons": ["indikator belum siap"]}
        rsi = ind.rsi(close, 14)
        sma20 = ind.sma(close, 20)
        close_last = close[-1]
        cross_up = prev["pdi"] <= prev["mdi"] and last["pdi"] > last["mdi"]
        cross_dn = prev["mdi"] <= prev["pdi"] and last["mdi"] > last["pdi"]

        action, score, reasons = "HOLD", 0, []
        ind_snap = {"last": close_last, "pdi": last["pdi"], "mdi": last["mdi"],
                    "adx": last["adx"], "rsi": rsi, "sma20": sma20}
        # ---- BUY ----
        if cross_up and last["adx"] >= 15:
            action, score = "BUY", 2
            reasons.append(f"+DI cross ABOVE -DI (golden cross), ADX {last['adx']}")
        elif last["pdi"] > last["mdi"] and last["adx"] >= 25:
            action, score = "BUY", 1
            reasons.append(f"trend bullish (+DI {last['pdi']} > -DI {last['mdi']}, ADX {last['adx']})")
        if action == "BUY":
            if rsi and rsi > 75:
                score -= 1
                reasons.append(f"RSI {rsi:.0f} overbought (risiko)")
            if sma20 and close_last < sma20:
                score -= 1
                reasons.append(f"harga {close_last} < SMA20 {sma20:.0f}")
            if score <= 0:
                action = "HOLD"
        # ---- SELL ----
        if action == "HOLD":
            if cross_dn and last["adx"] >= 15:
                action, score = "SELL", 2
                reasons.append(f"-DI cross ABOVE +DI (death cross), ADX {last['adx']}")
            elif last["mdi"] > last["pdi"] and last["adx"] >= 25:
                action, score = "SELL", 1
                reasons.append(f"trend bearish (-DI {last['mdi']} > +DI {last['pdi']}, ADX {last['adx']})")
            if action == "SELL":
                if rsi and rsi < 25:
                    score -= 1
                    reasons.append(f"RSI {rsi:.0f} oversold (risiko)")
                if sma20 and close_last > sma20:
                    score -= 1
                    reasons.append(f"harga {close_last} > SMA20 {sma20:.0f}")
                if score <= 0:
                    action = "HOLD"
        if action == "HOLD" and not reasons:
            reasons.append(f"ADX {last['adx']} +DI {last['pdi']} -DI {last['mdi']} RSI {rsi:.0f}")
        return {"code": code, "action": action, "score": score,
                "reasons": reasons, "ind": ind_snap, "interval": interval}

    def scan_signals(self, codes=None, interval="15m"):
        """Scan daftar saham (default: top values 15) -> list sinyal sorted by score."""
        import urllib.request, urllib.error
        if codes is None:
            tv = self.top_values(15)
            codes = [b["code"] for b in tv]
        results = []
        for c in codes:
            try:
                results.append(self.signal(c, interval))
            except Exception as e:
                results.append({"code": c, "action": "HOLD", "score": 0,
                                "reasons": [f"err: {e}"]})
        results.sort(key=lambda r: (r["action"] != "HOLD", -r["score"]))
        return results

    def execute_signals(self, results, min_score=1, live=False):
        """Eksekusi sinyal -> order (DRY-RUN default; live hanya dgn flag).

        BUY : place_order limit di harga real-time — SKIP kalau sudah punya posisi
              (anti-numpuk) — guard cash otomatis di place_order.
        SELL: place_order jual 1 lot — SKIP kalau tidak punya posisi saham itu.
        """
        positions = {}
        self.live = live  # override mode utk sesi eksekusi ini (DRY-RUN default)
        try:
            f = self.flat_positions()
            positions = {r["code"]: r for r in f.get("rows", [])}
        except Exception:
            positions = {}
        # sisa cash utk guard akumulasi (total order plan <= cash!)
        cash_left = None
        try:
            bal = self.get_balance()
            cash_left = (bal.get("data") or {}).get("cash")
        except Exception:
            pass
        executed = []
        for r in results:
            code = r["code"]
            if r["action"] == "BUY" and r["score"] >= min_score:
                if code in positions:
                    self.log(f"[SKIP] {code} sudah punya posisi ({positions[code]['qty']} lbr) — anti-numpuk")
                    continue
                px = self.real_time_price(code)
                price = px.get("last")
                if not price:
                    self.log(f"[SKIP] {code} harga n/a ({px.get('source')})")
                    continue
                price = int(round(price))
                qty_lot = max(int(ORDER_VALUE // (price * 100)), 1)
                # guard akumulasi: total semua order plan <= cash (anti over-leverage!)
                if cash_left is not None:
                    val = qty_lot * 100 * price
                    if val > cash_left:
                        self.log(f"[SKIP] {code} Rp{val:,.0f} > sisa cash Rp{cash_left:,.0f} (akumulasi)")
                        continue
                    cash_left -= val
                plan = self.place_order(code, qty_lot, is_buy=True, price=price,
                                        order_type="limit")
                if plan:
                    executed.append(plan)
            elif r["action"] == "SELL" and r["score"] >= min_score:
                if code not in positions:
                    self.log(f"[SKIP] {code} tidak punya posisi — tidak ada yg dijual")
                    continue
                px = self.real_time_price(code)
                price = int(round(px.get("last") or 0))
                if not price:
                    self.log(f"[SKIP] {code} harga n/a ({px.get('source')})")
                    continue
                plan = self.place_order(code, 1, is_buy=False, price=price,
                                        order_type="limit")
                if plan:
                    executed.append(plan)
        return executed

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
def market_open(now=None, open_h=MARKET_OPEN, close_h=MARKET_CLOSE):
    """True kalau weekday (Sen-Jum) & jam WIB dalam [open, close)."""
    import datetime as _dt
    now = now or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=7)))
    if now.weekday() >= 5:  # Sabtu/Minggu
        return False
    oh, om = map(int, open_h.split(":"))
    ch, cm = map(int, close_h.split(":"))
    mins = now.hour * 60 + now.minute
    return oh * 60 + om <= mins < ch * 60 + cm


def run_loop(bot, cycle_minutes=CYCLE_MINUTES, interval=SCAN_INTERVAL,
             auto_execute=AUTO_EXECUTE, min_score=1):
    """Loop scan sinyal tiap cycle_minutes (default 3 menit) saat market buka.

    Lapor SINYAL BARU (action/score berubah) — nggak spam yg sama.
    auto_execute=1 -> execute_signals (DRY-RUN kecuali bot.live).
    """
    import time as _t
    last_state = {}
    last_plan_hash = None
    bot.log(f"LOOP start: cycle {cycle_minutes}m | interval {interval} | "
            f"market {MARKET_OPEN}-{MARKET_CLOSE} WIB | execute={'LIVE' if bot.live else 'DRY-RUN'}")
    while True:
        try:
            if not market_open():
                bot.log("market CLOSED — tunggu jam pasar...")
                _t.sleep(60)
                continue
            res = bot.scan_signals(interval=interval)
            new_sig = []
            for r in res:
                if r["action"] == "HOLD":
                    continue
                key = (r["code"], r["action"])
                if last_state.get(key) != r["score"]:
                    last_state[key] = r["score"]
                    new_sig.append(r)
                    bot.log(f"SINYAL {r['action']} {r['code']} (skor {r['score']}): {r['reasons'][0]}")
            if auto_execute and (new_sig or True):
                act = [r for r in res if r["action"] != "HOLD"]
                if act:
                    plans = bot.execute_signals(act, min_score=min_score, live=bot.live)
                    if plans:
                        h = hash(tuple(sorted((p["symbol"], p["isBuy"], p["price"]) for p in plans)))
                        if h != last_plan_hash:
                            last_plan_hash = h
                            bot.log(f"ORDER PLAN ({len(plans)}): " + ", ".join(
                                f"{p['symbol']} {'BUY' if p['isBuy'] else 'SELL'} {p['qty_lot']}lot @{p['price']}"
                                for p in plans))
            if not new_sig:
                bot.log(f"scan ok ({len(res)} saham, tidak ada sinyal baru)")
        except Exception as e:
            bot.log(f"loop error: {e}")
        _t.sleep(max(cycle_minutes * 60, 10))


def main():
    live = "--live" in sys.argv
    symbols = None
    loop = "--loop" in sys.argv
    cycle = CYCLE_MINUTES
    interval = SCAN_INTERVAL
    auto_execute = AUTO_EXECUTE
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--symbols" and i + 1 < len(args):
            symbols = args[i + 1].split(",")
        if a == "--cycle" and i + 1 < len(args):
            cycle = float(args[i + 1])
        if a == "--interval" and i + 1 < len(args):
            interval = args[i + 1]
        if a == "--execute":
            auto_execute = True
    bot = ProfitsBot(live=live)
    bot.login()
    bot.trade_login()
    if live:
        print("!! LIVE MODE — order akan dikirim beneran !!")
    if loop:
        run_loop(bot, cycle_minutes=cycle, interval=interval, auto_execute=auto_execute)
        return
    bot.run_once(symbols)
    if not live:
        print("\n[DRY-RUN] Tidak ada order dikirim. Untuk live: python profits_bot.py --live")


if __name__ == "__main__":
    main()
