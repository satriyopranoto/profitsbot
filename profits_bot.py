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
pc.load_env()  # ⚠️ WAJIB SEBELUM config dievaluasi — kalau tidak .env nggak kebaca!
from profits_ws import parse_price
import indicators as ind

# ------------------------- konfigurasi -------------------------
SYMBOLS = os.environ.get("PROFITS_SYMBOLS", "BBCA,BBRI,ANTM").split(",")
PROTRADER_API = os.environ.get("PROTRADER_API", "http://127.0.0.1:8777")  # bot protrader (real-time PMP)
# --- chart ---
CHART_RESOLUTION = os.environ.get("PROFITS_CHART_RESOLUTION", "15")  # 1,3,5,15,30,45,60,120,240,D
CHART_COUNTBACK = int(os.environ.get("PROFITS_CHART_COUNTBACK", "2000"))  # max bar (best effort — Yahoo)
# --- indikator (basis ADX) ---
ADX_PERIOD = int(os.environ.get("PROFITS_ADX_PERIOD", "14"))  # period ADX (Wilder)
ADX_THRESHOLD = float(os.environ.get("PROFITS_ADX_THRESHOLD", "20"))  # minimal ADX utk sinyal tren
ADX_CROSS = float(os.environ.get("PROFITS_ADX_CROSS", "15"))  # ADX min utk deteksi cross
DONCHIAN_PERIOD = int(os.environ.get("PROFITS_DONCHIAN_PERIOD", "10"))  # SL lookback = 2.8x period
BOLLINGER_PERIOD = int(os.environ.get("PROFITS_BOLLINGER_PERIOD", "20"))
BOLLINGER_STD = float(os.environ.get("PROFITS_BOLLINGER_STD", "2"))
# --- watchlist & filter ---
TOP_VALUES = int(os.environ.get("PROFITS_TOP_VALUES", "15"))  # top N by value
FILTER_DISCRETE = os.environ.get("PROFITS_FILTER_DISCRETE", "1") == "1"  # skip saham flat
MAX_FLAT_PCT = float(os.environ.get("PROFITS_MAX_FLAT_PCT", "50"))  # threshold flat %
# --- mode & eksekusi ---
BOT_MODE = os.environ.get("PROFITS_BOT_MODE", "nontrade").lower()  # nontrade|trade
TRADE_LOT = int(os.environ.get("PROFITS_TRADE_LOT", "0"))  # lot/order (0 = sizing CAPITAL/RISK)
TEST_SYMBOL = os.environ.get("PROFITS_TEST_SYMBOL", "").upper()  # test cycle langsung di saham ini
USE_FLIP = os.environ.get("PROFITS_FLIP", os.environ.get("PROFITS_USE_FLIP", "1")) == "1"
CYCLE_MINUTES = float(os.environ.get("PROFITS_CYCLE_MINUTES", "3"))  # loop scan (menit)
SCAN_INTERVAL = os.environ.get("PROFITS_SCAN_INTERVAL", "15m")  # timeframe sinyal (Yahoo)
AUTO_EXECUTE = os.environ.get("PROFITS_AUTO_EXECUTE", "0") == "1"  # eksekusi otomatis (DRY-RUN)
MARKET_HOURS = os.environ.get("PROFITS_MARKET_HOURS", "0") == "1"  # 0 = 24 jam (testing); 1 = cuma jam bursa
MARKET_OPEN = os.environ.get("PROFITS_MARKET_OPEN", "09:00")  # jam pasar WIB (kalau MARKET_HOURS=1)
MARKET_CLOSE = os.environ.get("PROFITS_MARKET_CLOSE", "15:30")
# --- sizing / risk ---
CAPITAL = float(os.environ.get("PROFITS_CAPITAL", "100000000"))  # modal default 100 jt
RISK_PCT = float(os.environ.get("PROFITS_RISK_PCT", "1.0"))  # risk per posisi (%)
ORDER_VALUE = float(os.environ.get("PROFITS_ORDER_VALUE", "0"))  # budget/order (0 = sizing + sisa cash)
SL_DONCHIAN_PERIOD = int(os.environ.get("PROFITS_SL_DONCHIAN_PERIOD", str(DONCHIAN_PERIOD)))
FLIP = USE_FLIP
BUY_UPTREND_ONLY = os.environ.get("PROFITS_BUY_UPTREND_ONLY", "1") == "1"  # buy HANYA uptrend kuat
UPTREND_MIN_PCT = float(os.environ.get("PROFITS_UPTREND_MIN_PCT", "35"))  # ambang adx_sma_pct
TP_PCT = float(os.environ.get("PROFITS_TP_PCT", "0.5"))  # exit check: floating profit > %
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
    def check_exit(self, tp_pct=0.5):
        """Exit check — TAKE PROFIT dari holding (ala protraderbot exit_check).

        Untuk tiap posisi: floating profit > tp_pct (%) -> SELL (jual available).
        Return list {code, qty_lot, price, avg, flat_pct} — urut profit terbesar.
        """
        f = self.flat_positions()
        exits = []
        for r in f["rows"]:
            avg, cur, qty = r.get("avg") or 0, r.get("current") or 0, r.get("qty") or 0
            if qty <= 0 or avg <= 0 or cur <= 0:
                continue
            flat_pct = (cur - avg) / avg * 100
            if flat_pct > tp_pct:
                exits.append({"code": r["code"], "qty_lot": max(int(qty // 100), 1),
                              "price": cur, "avg": avg, "flat_pct": round(flat_pct, 2)})
        exits.sort(key=lambda z: -z["flat_pct"])
        return exits

    def execute_exits(self, exits, live=False):
        """Eksekusi exit plan (TAKE PROFIT) -> SELL order (DRY-RUN default)."""
        self.live = live
        done = []
        for e in exits:
            plan = self.place_order(e["code"], e["qty_lot"], is_buy=False,
                                    price=int(round(e["price"])), order_type="limit")
            if plan:
                done.append(plan)
        return done

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

    def signal(self, code, interval="15m", range_="5d", adx_n=None):
        """Analisis sinyal utk 1 saham (OHLC Yahoo) — PERSIS protraderbot.

        BUY : low>SL(Donchian) & close>SMA20 & ADX>ADX_THRESHOLD & ADX naik(5)
              & +DI>-DI & +DI naik(5)   [strict >, bukan cross, bukan >=]
        SELL: high<SL & close<SMA20 & ADX>ADX_THRESHOLD & ADX naik(5)
              & -DI>+DI & -DI naik(5)
        Filter tambahan: DISCRETE (flat %). Return {code, action, score, reasons[], ind{...}}.
        """
        adx_n = adx_n or ADX_PERIOD
        adx_thresh = ADX_THRESHOLD
        adx_cross = ADX_CROSS
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
        if not last:
            return {"code": code, "action": "HOLD", "score": 0,
                    "reasons": ["indikator belum siap"]}
        rsi = ind.rsi(close, 14)
        sma20 = ind.sma(close, 20)
        close_last = close[-1]
        # statistic bullish ala stocktrade: % bar ADX>25 & Close>SMA20 (window 100)
        adx_pct, adx_comment = ind.adx_sma_pct(s, close, ind.sma_series(close, 20))

        # filter DISCRETE: % bar flat (close == prev close) > MAX_FLAT_PCT -> skip
        flat_pct = 0.0
        if FILTER_DISCRETE and len(close) > 20:
            flat = sum(1 for i in range(1, len(close)) if close[i] == close[i - 1])
            flat_pct = 100.0 * flat / (len(close) - 1)

        action, score, reasons = "HOLD", 0, []
        ind_snap = {"last": close_last, "pdi": last["pdi"], "mdi": last["mdi"],
                    "adx": last["adx"], "rsi": rsi, "sma20": sma20,
                    "flat_pct": round(flat_pct, 1),
                    "adx_sma_pct": adx_pct, "trend_comment": adx_comment}
        if FILTER_DISCRETE and flat_pct > MAX_FLAT_PCT:
            return {"code": code, "action": "HOLD", "score": 0,
                    "reasons": [f"DISCRETE: {flat_pct:.0f}% bar flat (max {MAX_FLAT_PCT:.0f}%)"],
                    "ind": ind_snap, "interval": interval}
        # ---- sinyal PERSIS protraderbot (signal_buy / signal_sell) ----
        # BUY  : low>SL & close>SMA20 & ADX>thresh & ADX naik(5) & +DI>-DI & +DI naik(5)
        # SHORT: high<SL & close<SMA20 & ADX>thresh & ADX naik(5) & -DI>+DI & -DI naik(5)
        #        (sinyal bearish = SHORT — DI SINI = pemicu EXIT LONG, IDX cash ga bisa short)
        i = len(close) - 1
        s6 = s[-6] if len(s) >= 6 else None
        lookback = max(int(2.8 * DONCHIAN_PERIOD), 5)  # SL Donchian (2.8x period)
        dc = ind.donchian(close, lookback)
        sl_lower = dc["lower"] if dc else None
        if i >= 6 and s6 and sl_lower is not None and sma20 is not None:
            if (low[i] > sl_lower and close[i] > sma20
                    and last["adx"] > adx_thresh and last["adx"] > s6["adx"]
                    and last["pdi"] > last["mdi"] and last["pdi"] > s6["pdi"]):
                action, score = "BUY", 1
                reasons.append(
                    f"BUY: low {low[i]:.0f}>SL {sl_lower:.0f}, close {close[i]:.0f}>SMA20 {sma20:.0f}, "
                    f"ADX {last['adx']:.1f}>{adx_thresh:.0f} & naik, +DI {last['pdi']:.1f}>-DI {last['mdi']:.1f} & naik")
            elif (high[i] < sl_lower and close[i] < sma20
                    and last["adx"] > adx_thresh and last["adx"] > s6["adx"]
                    and last["mdi"] > last["pdi"] and last["mdi"] > s6["mdi"]):
                action, score = "SHORT", 1
                reasons.append(
                    f"SHORT: high {high[i]:.0f}<SL {sl_lower:.0f}, close {close[i]:.0f}<SMA20 {sma20:.0f}, "
                    f"ADX {last['adx']:.1f}>{adx_thresh:.0f} & naik, -DI {last['mdi']:.1f}>+DI {last['pdi']:.1f} & naik")
        if action == "HOLD" and not reasons:
            reasons.append(f"ADX {last['adx']} +DI {last['pdi']} -DI {last['mdi']} RSI {rsi:.0f}")
        return {"code": code, "action": action, "score": score,
                "reasons": reasons, "ind": ind_snap, "interval": interval}

    def scan_signals(self, codes=None, interval="15m"):
        """Scan daftar saham (default: top values TOP_VALUES — fallback SYMBOLS kalau kosong).

        top-stocks = data harian (di-clear 08:00 WIB) — kosong di luar jam pasar
        -> fallback ke PROFITS_SYMBOLS supaya loop tetap ada isinya saat testing.
        """
        import urllib.request, urllib.error
        values = {}
        if codes is None:
            tv = self.top_values(TOP_VALUES)
            codes = [b["code"] for b in tv] or SYMBOLS
            values = {b["code"]: b.get("val", 0) for b in tv}
            if not tv and not getattr(self, "_fb_warned", False):
                self._fb_warned = True
                self.log(f"top-stocks kosong (data harian di-clear) — fallback ke SYMBOLS: {codes}")
        results = []
        for c in codes:
            try:
                r = self.signal(c, interval)
                r["value"] = values.get(c, 0)  # likuiditas (nilai transaksi, jt)
                results.append(r)
            except Exception as e:
                results.append({"code": c, "action": "HOLD", "score": 0,
                                "reasons": [f"err: {e}"], "value": values.get(c, 0)})
        # ranking PERSIS stocktrade screener (line 2513 app.py):
        #   sort by (rekomendasi, adx_sma_pct = statistic bullish, value) desc
        action_rank = {"BUY": 3, "SHORT": 2, "HOLD": 0}
        results.sort(key=lambda r: (
            action_rank.get(r["action"], 0),
            (r.get("ind") or {}).get("adx_sma_pct", 0) or 0,
            r.get("value", 0) or 0
        ), reverse=True)
        return results

    def sl_donchian_plan(self, code, interval="15m"):
        """SL berbasis Donchian — lookback = 2.8 x DONCHIAN_PERIOD bar (spt protraderbot).

        Dari OHLC Yahoo: lower = min(close, lookback) — trigger = lower - 1 tick.
        Return {code, trigger, lower, upper} — trigger integer (harga IDX).
        """
        lookback = max(int(2.8 * DONCHIAN_PERIOD), 5)
        ohlc = self.fetch_ohlc(code, interval, "5d")
        if isinstance(ohlc, dict) or len(ohlc) < lookback:
            return {"code": code, "error": f"data kurang ({len(ohlc) if not isinstance(ohlc, dict) else '?'} < {lookback})"}
        closes = [x["c"] for x in ohlc]
        dc = ind.donchian(closes, lookback)
        if not dc:
            return {"code": code, "error": "donchian gagal"}
        trigger = max(int(dc["lower"]) - 1, 1)
        return {"code": code, "trigger": trigger,
                "lower": round(dc["lower"]), "upper": round(dc["upper"]),
                "lookback": lookback}

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
            if r["action"] == "BUY" and r["score"] >= min_score:
                code = r["code"]
                # syarat buy: HANYA uptrend kuat (statistic bullish >= UPTREND_MIN_PCT)
                ind_s = r.get("ind") or {}
                if BUY_UPTREND_ONLY and (ind_s.get("adx_sma_pct") or 0) < UPTREND_MIN_PCT:
                    self.log(f"[SKIP] {code} bukan uptrend kuat (bullish {ind_s.get('adx_sma_pct')}% < {UPTREND_MIN_PCT:.0f}%) — buy hanya uptrend kuat")
                    continue
                if code in positions:
                    self.log(f"[SKIP] {code} sudah punya posisi ({positions[code]['qty']} lbr) — anti-numpuk")
                    continue
                px = self.real_time_price(code)
                price = px.get("last")
                if not price:
                    self.log(f"[SKIP] {code} harga n/a ({px.get('source')})")
                    continue
                price = int(round(price))
                # SL utk sizing (risk-based) + rencana SL setelah posisi terisi
                sl = self.sl_donchian_plan(code, SCAN_INTERVAL)
                sl_price = sl.get("trigger") if sl and "trigger" in sl else None
                # ---- sizing lot ----
                if TRADE_LOT > 0:
                    qty_lot = TRADE_LOT  # lot tetap (1 = uji coba)
                elif sl_price and price != sl_price:
                    # risk-based (persis protraderbot sizing.py):
                    #   risk_amount = CAPITAL * RISK_PCT/100
                    #   lot = floor(risk_amount / (|price-sl| * 100))
                    risk_amt = CAPITAL * RISK_PCT / 100.0
                    qty_lot = max(int(risk_amt / (abs(price - sl_price) * 100)), 1)
                    self.log(f"  sizing {code}: risk Rp{risk_amt:,.0f} / (|{price}-{sl_price}|*100) = {qty_lot} lot")
                else:
                    budget = ORDER_VALUE if ORDER_VALUE > 0 else 10_000_000
                    qty_lot = max(int(budget // (price * 100)), 1)
                # cap budget ORDER_VALUE (kalau > 0)
                if ORDER_VALUE > 0:
                    qty_lot = min(qty_lot, max(int(ORDER_VALUE // (price * 100)), 1))
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
                    if sl_price:
                        plan["sl_donchian"] = sl_price
                        self.log(f"  SL plan {code}: trigger {sl_price} (lookback {sl.get('lookback')} bar, Donchian lower {sl.get('lower')})")
            elif r["action"] == "SHORT" and r["score"] >= min_score:
                code = r["code"]
                # sinyal SHORT = pemicu EXIT LONG (IDX cash-only: ga bisa short beneran)
                # -> jual posisi yang dipunya; kalau tidak punya -> skip
                if code not in positions:
                    self.log(f"[SKIP] {code} sinyal SHORT tapi tidak punya posisi — exit long skip (ga bisa short cash IDX)")
                    continue
                px = self.real_time_price(code)
                price = int(round(px.get("last") or 0))
                if not price:
                    self.log(f"[SKIP] {code} harga n/a ({px.get('source')})")
                    continue
                # FLIP=1 -> tutup posisi penuh; default -> jual 1 lot (test/trim)
                avail = positions[code].get("qty") or 0
                qty_lot = max(avail // 100, 1) if FLIP else 1
                self.log(f"  EXIT LONG {code}: sinyal SHORT -> jual {qty_lot} lot ({'penuh' if FLIP else '1 lot'})")
                plan = self.place_order(code, qty_lot, is_buy=False, price=price,
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
    """True kalau MARKET_HOURS=0 (24 jam — testing) ATAU weekday & jam WIB dalam [open, close)."""
    if not MARKET_HOURS:
        return True  # 24 jam — bisa test di luar jam bursa
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
            f"market {'24 JAM (testing)' if not MARKET_HOURS else f'{MARKET_OPEN}-{MARKET_CLOSE} WIB'} | "
            f"execute={'LIVE' if bot.live else 'DRY-RUN'}")
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
            # EXIT CHECK — TAKE PROFIT dari holding (ala protraderbot)
            try:
                exits = bot.check_exit(tp_pct=TP_PCT)
                if exits:
                    for e in exits:
                        bot.log(f"EXIT TP {e['code']}: +{e['flat_pct']}% (avg {e['avg']:.0f} -> {e['price']:.0f})")
                    if auto_execute:
                        plans = bot.execute_exits(exits, live=bot.live)
                        if plans:
                            bot.log(f"EXIT ORDER PLAN ({len(plans)}): " + ", ".join(
                                f"SELL {p['symbol']} {p['qty_lot']}lot @{p['price']}" for p in plans))
            except Exception as e:
                bot.log(f"exit check error: {e}")
            if not new_sig:
                bot.log(f"scan ok ({len(res)} saham, tidak ada sinyal baru)")
        except Exception as e:
            bot.log(f"loop error: {e}")
        _t.sleep(max(cycle_minutes * 60, 10))


def main():
    # mode: nontrade (DRY-RUN, default) | trade (kirim order beneran)
    mode = BOT_MODE
    args = sys.argv[1:]
    if "--live" in args or "--trade" in args:
        mode = "trade"
    if "--nontrade" in args or "--dry-run" in args:
        mode = "nontrade"
    live = mode == "trade"
    symbols = None
    loop = "--loop" in args
    cycle = CYCLE_MINUTES
    interval = SCAN_INTERVAL
    auto_execute = AUTO_EXECUTE
    for i, a in enumerate(args):
        if a == "--symbols" and i + 1 < len(args):
            symbols = args[i + 1].split(",")
        if a == "--cycle" and i + 1 < len(args):
            cycle = float(args[i + 1])
        if a == "--interval" and i + 1 < len(args):
            interval = args[i + 1]
        if a == "--execute":
            auto_execute = True
    if not symbols and TEST_SYMBOL:
        symbols = [TEST_SYMBOL]  # TEST_SYMBOL=BBCA -> test cycle langsung di saham itu
    bot = ProfitsBot(live=live)
    bot.login()
    bot.trade_login()
    if live:
        print("!! TRADE MODE — order akan dikirim beneran !!")
    else:
        print("[NONTRADE/DRY-RUN] scan & log saja, tidak ada order dikirim.")
    if loop:
        run_loop(bot, cycle_minutes=cycle, interval=interval, auto_execute=auto_execute)
        return
    bot.run_once(symbols)
    if not live:
        print("\n[DRY-RUN] Tidak ada order dikirim. Untuk live: python profits_bot.py --live")


if __name__ == "__main__":
    main()
