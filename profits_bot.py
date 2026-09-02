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
SCAN_INTERVAL = os.environ.get("PROFITS_SCAN_INTERVAL", "15m")  # timeframe sinyal — SOURCE OF TRUTH utk resolution chart (res_map di fetch_ohlc; countback=2000 hardcoded) 
# --- indikator (basis ADX) ---
ADX_PERIOD = int(os.environ.get("PROFITS_ADX_PERIOD", "14"))  # period ADX (Wilder)
ADX_THRESHOLD = float(os.environ.get("PROFITS_ADX_THRESHOLD", "20"))  # minimal ADX utk sinyal tren
ADX_CROSS = float(os.environ.get("PROFITS_ADX_CROSS", "15"))  # ADX min utk deteksi cross
DONCHIAN_PERIOD = int(os.environ.get("PROFITS_DONCHIAN_PERIOD", "10"))  # SL lookback = 2.8x period
DONCHIAN_MULTIPLE = float(os.environ.get("PROFITS_DONCHIAN_MULTIPLE", "2.8"))  # SL multiple
# Switch SL (paritas EA/protraderbot/usbot): sl = ac==1 ? s(low) : r(high). Saat regime
# DOWN (ac=-1) sl = band ATAS => high<sl mudah -> sinyal SHORT/FLIP lebih awal. Flip
# tetap HANYA kalau rumus short PENUH terpenuhi (bukan semata regime change).
# 1 = selalu switch (default); 0 = legacy (Donchian lower dari close).
PROFITS_SWITCH_SL = os.environ.get("PROFITS_SWITCH_SL", "1") == "1"
SWITCH_ERO = max(int(DONCHIAN_MULTIPLE * DONCHIAN_PERIOD), 5)
BOLLINGER_PERIOD = int(os.environ.get("PROFITS_BOLLINGER_PERIOD", "20"))
BOLLINGER_STD = float(os.environ.get("PROFITS_BOLLINGER_STD", "2"))
# --- watchlist & filter ---
TOP_VALUES = int(os.environ.get("PROFITS_TOP_VALUES", "15"))  # top N by value
# Min nilai transaksi (Rp) utk lolos filter top-stocks — skip saham kecil/garing
# saat market dry (buang SLIS/GPRA/ADMR/INCO 7-12M). 0 = nonaktif.
MIN_TOP_VAL = int(os.environ.get("PROFITS_MIN_TOP_VAL", "15000000000"))
# HANYA beli saham harga >= MIN_PRICE (RUPIAH PENUH, mis. 100; 0 = nonaktif).
# Filter fundamental — cegah saham murah ikut terbeli. Berlaku HANYA utk beli;
# saham yg sudah di holding tetap boleh dijual (SHORT/TP exit tanpa filter harga).
MIN_PRICE = int(os.environ.get("PROFITS_MIN_PRICE", "0"))
FILTER_DISCRETE = os.environ.get("PROFITS_FILTER_DISCRETE", "1") == "1"  # skip saham flat
MAX_FLAT_PCT = float(os.environ.get("PROFITS_MAX_FLAT_PCT", "50"))  # threshold flat %
# --- RSI filter (paritas EA Basis_ADX_RSI & protraderbot) ---
# USE_RSI_FILTER=1: BUY long HANYA kalau RSI > RSI_BUY_MIN (default 70),
# SHORT/FLIP HANYA kalau RSI < RSI_SELL_MAX (default 30). Anti-sideway.
USE_RSI_FILTER = os.environ.get("PROFITS_USE_RSI_FILTER", "0") == "1"
RSI_BUY_MIN = float(os.environ.get("PROFITS_RSI_BUY_MIN", "70"))
RSI_SELL_MAX = float(os.environ.get("PROFITS_RSI_SELL_MAX", "30"))
# --- mode & eksekusi ---
BOT_MODE = os.environ.get("PROFITS_BOT_MODE", "nontrade").lower()  # nontrade|trade
TRADE_LOT = int(os.environ.get("PROFITS_TRADE_LOT", "0"))  # lot/order (0 = sizing CAPITAL/RISK)
TEST_SYMBOL = os.environ.get("PROFITS_TEST_SYMBOL", "").upper()  # test cycle langsung di saham ini
USE_FLIP = os.environ.get("PROFITS_FLIP", os.environ.get("PROFITS_USE_FLIP", "1")) == "1"
CYCLE_MINUTES = float(os.environ.get("PROFITS_CYCLE_MINUTES", "3"))  # loop scan (menit)
AUTO_EXECUTE = (BOT_MODE == "trade")  # otomatis: nontrade = scan&log; trade = eksekusi real
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
# Guard statistic bullish "last N bar" utk hindari pct palsu-tinggi saat OHLC pendek
# (kasus VKTR 2026-08-27: window ~30-40 bar of rally -> adx_sma_pct 100% padahal sideways).
ADX_PCT_WINDOW = int(os.environ.get("PROFITS_ADX_PCT_WINDOW", "100"))  # jendela statistik (bar)
ADX_PCT_MIN_BARS = int(os.environ.get("PROFITS_ADX_PCT_MIN_BARS", "60"))  # min bar valid utk dipercaya
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
            print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

    # ---- auth ----
    def login(self):
        pc.load_env()
        u = os.environ.get("PROFITS_USERNAME")
        p = os.environ.get("PROFITS_PASSWORD")
        r = pc.login(u, p)
        if not pc._session:
            raise RuntimeError(f"login gagal: {r}")
        _tok_ts["t"] = time.time()  # token fresh — jangan langsung refresh
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
        if not rt:
            # session kehilangan refreshToken -> full re-login, bukan cuma refresh
            self.log("refreshToken kosong — re-login penuh")
            try:
                self.login()
            except Exception as e:
                self.log("re-login gagal:", e)
            return
        r = pc._req("POST", "/identity/refresh", {"refreshToken": rt})
        tok = (r.get("data") or {}).get("token") or r.get("data") or r.get("token")
        if tok and tok.get("accessToken"):
            pc._session = tok
            _tok_ts["t"] = time.time()
            self.log("token refreshed")
        else:
            # refresh ditolak (400/401) -> session basi -> re-login penuh
            self.log("refresh gagal:", json.dumps(r)[:150])
            try:
                self.login()
            except Exception as e:
                self.log("re-login setelah refresh gagal:", e)

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
            _trade_ts["t"] = time.time()
            self.log("trade login OK (PIN)")
        else:
            self.log("trade login GAGAL:", json.dumps(r, ensure_ascii=False)[:200])
        return pc._trade_session

    def ensure_trade_token(self):
        """Jamin trade token valid — refresh kalau basi, re-login kalau
        refresh ditolak. (Self-healing trade session — sebelumnya cuma cek
        ADA/TIDAK, token basi -> SEMUA /portfolio/* & order 401 UNAUTHORIZED.)"""
        s = pc._trade_session
        if not s:
            self.trade_login()
            s = pc._trade_session
            if not s:
                return None
        exp = s.get("accessExpired") or 3600
        if (time.time() - _trade_ts.get("t", 0)) > max(exp - 120, 60):
            rt = s.get("refreshToken")
            if rt:
                try:
                    r = pc._req("POST", "/identity/trade/refresh",
                                {"refreshToken": rt})
                    tok = (r.get("data") or {}).get("token") or \
                        (r.get("data") if isinstance(r.get("data"), dict) else None)
                    if tok and tok.get("accessToken"):
                        pc._trade_session = tok
                        _trade_ts["t"] = time.time()
                        self.log("trade token refreshed")
                        return tok.get("accessToken")
                except Exception as e:
                    self.log("trade refresh gagal:", e)
            # refresh kosong/ditolak -> re-login penuh
            self.log("trade token basi — re-login trade penuh")
            try:
                self.trade_login()
            except Exception as e:
                self.log("re-login trade gagal:", e)
        return pc._trade_session.get("accessToken") if pc._trade_session else None

    # ---- data pasar ----
    def top_values(self, n=15):
        """Top values: /trade-book/trade-book/top-stocks — sort by nilai (val).

        Format: [{buy: {code, curr, change, val, freq, lot, avg}, sell: {...}}]
        Ambil item teratas dari sisi buy (val terbesar).
        FILTER (paritas protraderbot):
          - REGULAR: kode 4 huruf kapital (^[A-Z]{4}$) — buang saham kecil/liar
          - MIN_VAL: skip kalau val < MIN_TOP_VAL (anti saham garing saat market dry)
        """
        import re as _re
        r = pc._req("GET", "/trade-book/trade-book/top-stocks", token=self.ensure_token())
        items = r.get("data") or []
        self._top_error = ""
        if not items and r.get("message"):
            self._top_error = str(r.get("message"))[:120]
        rows = []
        filt_fmt = filt_val = 0
        for it in items:
            b = it.get("buy") or {}
            code = str(b.get("code") or "")
            val = b.get("val") or 0
            if not _re.match(r"^[A-Z]{4}$", code):
                filt_fmt += 1  # bukan regular stock 4 huruf — buang
                continue
            if val < MIN_TOP_VAL:
                filt_val += 1  # di bawah floor likuiditas — buang
                continue
            rows.append((val, b))
        # Beda-kan "API kosong" vs "semua kena filter" biar diagnosa akurat
        # (kasus 2026-08-26: top-stocks balik 50 item tapi 0 lolos karena
        # MIN_TOP_VAL=15B di market dry -> log lama nyasar "server di-clear?").
        if not rows and items:
            self._top_error = (
                f"data API ada ({len(items)} item) tapi SEMUA dikeluarkan filter: "
                f"{filt_fmt} bukan [A-Z]{4}, {filt_val} val < MIN_TOP_VAL({MIN_TOP_VAL:.0f})"
            )
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
        self.ensure_trade_token()
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
    def check_exit(self, tp_pct=0.5, dc_mult=2.8, dc_per=10):
        """Exit check — TAKE PROFIT pakai SL DONCHIAN (trailing), paritas EA Strong klasik.

        SELL jika: floating_pct > tp_pct  AND  close < sl (Donchian).
        - floating_pct = (current - avg) / avg * 100   (avg dari holding)
        - sl = SWITCH SL (ac==1?s:r, SL paritas protraderbot) saat PROFITS_SWITCH_SL=1
          => di regime DOWN sl = band ATAS, exit TP lebih awal; legacy (0) = LLV (min low).
        Jadi profit > 0,5% BELUM dijual — baru jual kalau close balik tembus
        SL Donchian (trailing trigger). BUKAN jual langsung di +0,5%!
        """
        f = self.flat_positions()
        rows = f["rows"]
        live = self._live_prices([r["code"] for r in rows],
                                 {r["code"]: r["current"] for r in rows})
        exits = []
        for r in rows:
            avg, cur, qty = (r.get("avg") or 0, live.get(r["code"]) or 0,
                             r.get("qty") or 0)
            if qty <= 0 or avg <= 0 or cur <= 0:
                continue
            flat_pct = (cur - avg) / avg * 100
            if flat_pct <= tp_pct:
                continue  # syarat 1: floating > tp_pct
            # syarat 2 (AND): close < SL DONCHIAN (trailing trigger).
            # Switch SL (paritas protraderbot) saat aktif, else LLV legacy.
            sl = (self.sl_donchian_switch(r["code"], SCAN_INTERVAL, dc_mult, dc_per)
                  if PROFITS_SWITCH_SL
                  else self.sl_donchian_price(r["code"], SCAN_INTERVAL, dc_mult, dc_per))
            if sl is None:
                continue  # SL n/a -> jangan jual (fail-safe)
            if cur >= sl:
                continue  # harga BELUM balik tembus SL -> HOLD
            exits.append({"code": r["code"], "qty_lot": max(int(qty // 100), 1),
                          "price": cur, "avg": avg, "flat_pct": round(flat_pct, 2),
                          "sl": round(sl)})
        exits.sort(key=lambda z: -z["flat_pct"])
        return exits

    def sl_donchian_price(self, code, interval="15m", dc_mult=2.8, dc_per=10):
        """SL Donchian high/low asli (paritas EA Strong / protraderbot donchian_sl).

        Lookback = dc_mult x dc_per bar. Utk posisi LONG: SL = min(low, lookback)
        (LLV). Return float atau None kalau data kurang.
        """
        lookback = max(int(dc_mult * dc_per), 5)
        ohlc = self.fetch_ohlc(code, interval, "5d")
        if isinstance(ohlc, dict) or len(ohlc) < lookback:
            return None
        lows = [x.get("l") for x in ohlc[-lookback:]]
        if not lows or any(x is None for x in lows):
            return None
        return min(lows)

    def sl_donchian_switch(self, code, interval="15m", dc_mult=2.8, dc_per=10):
        """SL SWITCH utk EXIT/TP-trailing (paritas protraderbot check_exit donchian_sl).

        sl = ac==1 ? s(lowest low) : r(highest high); ac = arah Donchian-breakout
        terakhir (ffill). Saat regime DOWN (ac=-1) sl = band ATAS => close < sl mudah
        => exit TP lebih awal (paritas protraderbot). Return float / None kalau data
        kurang. HANYA utk jalur exit; pasang SL order tetap pakai sl_donchian_price (LLV).
        """
        guard = max(int(dc_mult * dc_per), 5)
        ohlc = self.fetch_ohlc(code, interval, "5d")
        if isinstance(ohlc, dict) or not ohlc or len(ohlc) < guard:
            return None
        hi = [x["h"] for x in ohlc]
        lo = [x["l"] for x in ohlc]
        sl_arr = ind.donchian_sl_switch(hi, lo, dc_mult, dc_per)
        return sl_arr[-1] if sl_arr else None

    def basis_price(self, code, interval="15m", basis_period=20):
        """Basis = SMA20 close terakhir (paritas EA TPBasis / protraderbot).

        Dari OHLC Yahoo. Return float atau None kalau data kurang.
        """
        ohlc = self.fetch_ohlc(code, interval, "5d")
        if isinstance(ohlc, dict) or len(ohlc) < basis_period:
            return None
        closes = [x["c"] for x in ohlc]
        try:
            return ind.sma(closes, basis_period)
        except Exception:
            return None

    def order_book(self, code):
        """Bid/ask bersih via /catalog/company/<CODE>/order-book.

        Return {'bid': best_bid, 'ask': best_ask} atau {} kalau gagal.
        bids diurut tertinggi -> best bid = bids[0]; offers terendah -> ask = offers[0].
        """
        try:
            r = pc._req("GET", f"/catalog/company/{code}/order-book",
                        token=self.ensure_token())
            d = r.get("data") or {}
            bids, offers = d.get("bids") or [], d.get("offers") or []
            out = {}
            if bids:
                out["bid"] = bids[0]["price"]
            if offers:
                out["ask"] = offers[0]["price"]
            return out
        except Exception:
            return {}

    def best_bid(self, code):
        """Best bid — jual DI BID (persis protraderbot FLIP 'jual di bid')."""
        return self.order_book(code).get("bid")

    def best_ask(self, code):
        """Best ask — beli DI ASK (persis protraderbot: order di offer side)."""
        return self.order_book(code).get("ask")

    def execute_exits(self, exits, live=False):
        """Eksekusi exit plan (TAKE PROFIT) -> SELL DI BID (DRY-RUN default).

        Jual di best bid biar LANGSUNG kena (persis protraderbot FLIP:
        'jual di bid') — bukan limit di last yang bisa ngantri & ngunci posisi.
        """
        self.live = live
        done = []
        for e in exits:
            bid = self.best_bid(e["code"]) or e.get("price")
            self.log(f"  jual DI BID {e['code']}: bid {bid} (last {e.get('price')})")
            plan = self.place_order(e["code"], e["qty_lot"], is_buy=False,
                                    price=int(bid), order_type="limit")
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
        self.ensure_trade_token()
        return pc._req("GET", "/portfolio/balance", token=pc._trade_session.get("accessToken") if pc._trade_session else None)

    def get_stocks(self):
        self.ensure_trade_token()
        return pc._req("GET", "/portfolio/stock", token=pc._trade_session.get("accessToken") if pc._trade_session else None)

    def get_orders(self):
        self.ensure_trade_token()
        return pc._req("GET", "/portfolio/order", token=pc._trade_session.get("accessToken") if pc._trade_session else None)

    def get_orders_done(self):
        self.ensure_trade_token()
        return pc._req("GET", "/portfolio/order/done", token=pc._trade_session.get("accessToken") if pc._trade_session else None)

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
        # guard CASH: HANYA utk BUY — nilai order (RUPIAH) harus <= cash real.
        # SELL (jual) TIDAK butuh cash (malah menambah cash) — jangan di-blokir!
        if order_value and is_buy:
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
        self.ensure_trade_token()
        req = pc._req("POST", "/portfolio/order", payload,
                      token=pc._trade_session.get("accessToken"),
                      extra={"X-APP-FORM": "ro"})
        self.log("[LIVE] order:", json.dumps(req, ensure_ascii=False)[:300])
        if req and req.get("data"):  # sukses -> {data: <orderUUID>}
            plan["order_id"] = req["data"]
            plan["mode"] = "LIVE"
            return plan
        self.log(f"[LIVE] order GAGAL {code}: {json.dumps(req, ensure_ascii=False)[:200]}")
        return None

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
        self.ensure_trade_token()
        r = pc._req("POST", "/automation/stoploss", payload,
                    token=pc._trade_session.get("accessToken"))
        self.log("[LIVE] stop loss:", json.dumps(r, ensure_ascii=False)[:250])
        return r

    def get_stop_losses(self):
        self.ensure_trade_token()
        return pc._req("GET", "/automation/stoploss",
                       token=pc._trade_session.get("accessToken"))

    def cancel_automation(self, auto_id, auto_type="stoploss"):
        """Cancel automation: POST /automation/<type>/<id>/cancel.

        TERVERTIFIKASI: type WAJIB di URL (mis. "stoploss") —
        /automation/<id>/cancel -> 404 NOT_FOUND!
        """
        self.ensure_trade_token()
        return pc._req("POST", f"/automation/{auto_type}/{auto_id}/cancel",
                       token=pc._trade_session.get("accessToken"))

    def cancel_order(self, order_id):
        self.ensure_trade_token()
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
    def fetch_ohlc(self, code, interval="15m", range_="5d", min_bars=0):
        """OHLC multi-source (fallback chain):

        1. Bot protrader API lokal (/chart/<CODE>) — OHLC ChartCloud POEMS real-time
        2. Yahoo Finance .JK (delay ~10 menit) — kalau bot protrader mati
        min_bars: utk scanning (adx_sma_pct 'last N bar') minta history cukup — kalau
        tidak, statistic bisa dihitung dari jendela pendek & melonjak (kasus VKTR).
        Return list dict {t: epoch, o,h,l,c, v} urut waktu / {error: ...}.
        """
        import urllib.request, urllib.error
        # 1) protrader api_server: OHLC asli ChartCloud POEMS
        res_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "45m": "45",
                   "60m": "60", "1h": "60", "1d": "D", "D": "D"}
        url = (f"{PROTRADER_API}/chart/{code}"
               f"?resolution={res_map.get(interval, '15')}"
               f"&countback=2000&days_back=10")
        req = urllib.request.Request(url, headers={"User-Agent": "profitsbot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                d = json.loads(resp.read().decode())
            rows = d.get("data")
            # ChartCloud dingin/sepi bisa balik JUSTRU terlalu pendek (kasus MDIA:
            # cuma 15 bar) padahal Yahoo punya 113 bar. Data < lookback SL (28)
            # gak cukup utk Donchian/ADX -> jangan dipakai, turun ke fallback Yahoo.
            # Kalau min_bars diset (scan), butuh bar sebanyak itu biar statistic valid.
            if isinstance(rows, list) and len(rows) >= max(28, min_bars):
                return rows
        except Exception:
            pass
        # 2) fallback Yahoo (delay) — coba range makin panjang utk saham tipis/kurang
        #    data (kasus MDIA: 5d cuma ~15 bar close valid padahal 1mo = 260).
        for range_opt in [range_, "1mo", "3mo", "1y"]:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.JK"
                   f"?range={range_opt}&interval={interval}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    r = json.loads(resp.read().decode())
            except Exception as e:
                if range_opt == "1y":
                    return {"error": str(e)}
                continue
            res = (r.get("chart", {}).get("result") or [])
            if not res:
                if range_opt == "1y":
                    return {"error": "kosong"}
                continue
            ts = res[0].get("timestamp") or []
            q = (res[0].get("indicators", {}).get("quote") or [{}])[0]
            rows = []
            for i in range(len(ts)):
                if q["close"][i] is None:
                    continue
                rows.append({"t": ts[i], "o": q["open"][i], "h": q["high"][i],
                             "l": q["low"][i], "c": q["close"][i], "v": q["volume"][i]})
            if len(rows) >= max(28, min_bars) or range_opt == "1y":
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

    def _live_prices(self, codes, fallback_map=None):
        """Harga live PMP utk BANYAK kode PARALEL (via api_server 8777).

        /price butuh ~2-6s per kode kalau cache api_server (TTL 5s) dingin
        (pmp_ask.exe) — parallel biar 14 posisi selesai ~20s, bukan 84s.
        Tanpa fallback Yahoo (lambat) — display & keputusan TP. Gagal ->
        pakai nilai fallback_map (harga portfolio)."""
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor
        out = dict(fallback_map or {})
        if not codes:
            return out  # 0 posisi -> jangan buat ThreadPoolExecutor(0) (crash)

        def _one(code):
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        f"{PROTRADER_API}/price/{code}",
                        headers={"User-Agent": "profitsbot/1.0"}), timeout=8) as resp:
                    d = json.loads(resp.read().decode())
                pv = d.get("last") or d.get("bid") or d.get("ask")
                if pv:
                    return code, float(pv)
            except Exception:
                pass
            return code, None

        with ThreadPoolExecutor(max_workers=min(len(codes), 4)) as ex:
            for code, pv in ex.map(_one, codes):
                if pv is not None:
                    out[code] = pv
        return out

    def _live_price(self, code, fallback=0.0):
        """Harga live 1 kode (wrapper _live_prices)."""
        return self._live_prices([code], {code: fallback}).get(code, fallback)

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
        ohlc = self.fetch_ohlc(code, interval, range_, min_bars=ADX_PCT_WINDOW)
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
        # statistic bullish ala stocktrade: % bar ADX>adx_thresh & Close>SMA20 (window 100).
        # WAJIB adx_min = ADX_THRESHOLD config (bukan default 25) — selaraskan dgn sinyal
        # biar gate UPTREND_MIN_PCT konsisten. (paritas fix protraderbot c04d7e7, kasus JAST.)
        adx_pct, adx_comment, adx_valid = ind.adx_sma_pct(s, close, ind.sma_series(close, 20),
                                                  adx_min=adx_thresh)
        # Guard data pendek (kasus VKTR 2026-08-27): kalau bar valid < ADX_PCT_MIN_BARS,
        # statistik "last N bar" cuma diproses dari jendela kecil (isi rally) -> pct
        # palsu-tinggi (100%) padahal bukan uptrend kuat. Null-kan pct -> gate SKIP.
        if adx_valid < ADX_PCT_MIN_BARS:
            adx_pct = 0.0
            adx_comment = f"Data kurang ({adx_valid} bar<{ADX_PCT_MIN_BARS}) — statistik tdk dipercaya"

        # filter DISCRETE: % bar flat (close == prev close) > MAX_FLAT_PCT -> skip
        flat_pct = 0.0
        if FILTER_DISCRETE and len(close) > 20:
            flat = sum(1 for i in range(1, len(close)) if close[i] == close[i - 1])
            flat_pct = 100.0 * flat / (len(close) - 1)

        # SL Donchian (2.8x period) — dipakai utk ind_snap & log.
        # PROFITS_SWITCH_SL=1: sl = switch (ac==1?s:r) paritas EA/protraderbot/usbot —
        # di regime DOWN sl = band atas => sinyal SHORT/FLIP lebih awal (fix propagasi
        # error dari profitsbot yang jadi acuan usbot; usbot udah switch).
        lookback = max(int(DONCHIAN_MULTIPLE * DONCHIAN_PERIOD), 5)
        if PROFITS_SWITCH_SL:
            sl_arr = ind.donchian_sl_switch(high, low, DONCHIAN_MULTIPLE, DONCHIAN_PERIOD)
            sl_lower = sl_arr[-1] if sl_arr else None
        else:
            dc = ind.donchian(close, lookback)
            sl_lower = dc["lower"] if dc else None

        action, score, reasons = "HOLD", 0, []
        ind_snap = {"last": close_last, "pdi": last["pdi"], "mdi": last["mdi"],
                    "adx": last["adx"], "rsi": rsi, "sma20": sma20,
                    "sl": sl_lower,
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
        if i >= 6 and s6 and sl_lower is not None and sma20 is not None:
            if (low[i] > sl_lower and close[i] > sma20
                    and last["adx"] > adx_thresh and last["adx"] > s6["adx"]
                    and last["pdi"] > last["mdi"] and last["pdi"] > s6["pdi"]
                    and (rsi is None or not USE_RSI_FILTER or rsi > RSI_BUY_MIN)):
                action, score = "BUY", 1
                reasons.append(
                    f"BUY: low {low[i]:.0f}>SL {sl_lower:.0f}, close {close[i]:.0f}>SMA20 {sma20:.0f}, "
                    f"ADX {last['adx']:.1f}>{adx_thresh:.0f} & naik, +DI {last['pdi']:.1f}>-DI {last['mdi']:.1f} & naik"
                    + (f", RSI {rsi:.0f}>{RSI_BUY_MIN:.0f}" if (USE_RSI_FILTER and rsi is not None) else ""))
            elif (high[i] < sl_lower and close[i] < sma20
                    and last["adx"] > adx_thresh and last["adx"] > s6["adx"]
                    and last["mdi"] > last["pdi"] and last["mdi"] > s6["mdi"]
                    and (rsi is None or not USE_RSI_FILTER or rsi < RSI_SELL_MAX)):
                action, score = "SHORT", 1
                reasons.append(
                    f"SHORT: high {high[i]:.0f}<SL {sl_lower:.0f}, close {close[i]:.0f}<SMA20 {sma20:.0f}, "
                    f"ADX {last['adx']:.1f}>{adx_thresh:.0f} & naik, -DI {last['mdi']:.1f}>+DI {last['pdi']:.1f} & naik"
                    + (f", RSI {rsi:.0f}<{RSI_SELL_MAX:.0f}" if (USE_RSI_FILTER and rsi is not None) else ""))
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
        src = "inline"
        if codes is None:
            tv = self.top_values(TOP_VALUES) or []
            codes = [b["code"] for b in tv] or SYMBOLS
            values = {b["code"]: b.get("val", 0) for b in tv}
            src = "top-stocks(Profits)" if tv else "SYMBOLS fallback"
            if not tv and not getattr(self, "_fb_warned", False):
                self._fb_warned = True
                why = getattr(self, "_top_error", "") or "data kosong (server di-clear?)"
                self.log(f"top-stocks kosong/gagal ({why}) — fallback ke SYMBOLS")
        # transparansi scanner ala protraderbot: tampilkan SUMBER + daftar watchlist
        # yang di-scan, biar jelas scan dari top-values (bukan "dari thin air").
        self.log(f"[SCAN] watchlist {len(codes)} saham dari {src}")
        self.log("  " + " ".join(f"{c}:{values.get(c, 0)/1e9:.1f}B" for c in codes))
        results = []
        for c in codes:
            try:
                r = self.signal(c, interval)
                r["value"] = values.get(c, 0)  # likuiditas (nilai transaksi, jt)
                results.append(r)
            except Exception as e:
                results.append({"code": c, "action": "HOLD", "score": 0,
                                "reasons": [f"err: {e}"], "value": values.get(c, 0)})
        # Filter harga minimum (opsional): tandai BUY harga < MIN_PRICE utk
        # ditampilkan SKIP-PRICE di listing scan (tidak ikut dibeli). Berlaku
        # HANYA utk beli — SHORT (exit long) & TP tetap jalan tanpa filter.
        # Paritas protraderbot MIN_PRICE.
        if MIN_PRICE > 0:
            for r in results:
                if r["action"] == "BUY":
                    last_px = (r.get("ind") or {}).get("last") or 0
                    if last_px and last_px < MIN_PRICE:
                        r["price_skip"] = True
                        r.setdefault("reasons", []).append(
                            f"PRICE-SKIP: harga {last_px:.0f} < MIN_PRICE({MIN_PRICE}) "
                            f"— filter fundamental (beli hanya harga >= {MIN_PRICE})")
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

    def reconcile_sl(self, dc_mult=None, dc_per=None):
        """Auto-pasang Stop Loss utk SEMUA posisi yang belum ber-SL.

        Reconciliation (insiden 2026-08-25: posisi 'yatim' tanpa SL). Persis
        logika mass_sl_setup.py yang TERBUKTI live: SL = min(low, lookback
        2.8x10 bar), qty = LOT (total//100), SKIP yang sudah ber-SL (tidak
        ditimpa) & yang SL>=current (sudah tembus). Set_stop_loss cuma jalan
        kalau self.live (kalau tidak -> DRY-RUN plan di-log).

        Return (placed:list[code], missing:list[code], skipped:list[str]).
        """
        dc_mult = dc_mult or DONCHIAN_MULTIPLE
        dc_per = dc_per or DONCHIAN_PERIOD
        self.ensure_trade_token()
        st = self.get_stocks()
        rows = st.get("data") or []
        qtys = {x.get("code"): max(int((x.get("total") or 0) // 100), 1)
                for x in rows if (x.get("total") or 0) > 0}
        sls = self.get_stop_losses()
        sls_data = sls.get("data") or []
        if isinstance(sls_data, dict):
            sls_data = sls_data.get("list") or sls_data.get("items") or []
        have_sl = {s.get("code") for s in sls_data}
        placed, missing, skipped = [], [], []
        for code in qtys:
            if code in have_sl:
                continue  # sudah ber-SL — jangan timpa
            sl = self.sl_donchian_price(code, SCAN_INTERVAL, dc_mult, dc_per)
            if sl is None:
                skipped.append(f"{code}(ohlc n/a)")
                missing.append(code)
                self.log(f"SL reconcile {code}: OHLC n/a -> SKIP, butuh level manual")
                continue
            # skip kalau SL >= current (tembus -> langsung ke-trigger, sia-sia)
            try:
                px = self.get_price(code)
                cur = (px or {}).get("last") or (px or {}).get("sellPrice") or \
                      (px or {}).get("price") or 0
            except Exception:
                cur = 0
            if cur and sl >= cur:
                skipped.append(f"{code}(tembus sl{int(sl)}>=cur{int(cur)})")
                missing.append(code)
                self.log(f"SL reconcile {code}: SL {int(sl)} >= current {int(cur)} (tembus) -> SKIP, butuh level manual")
                continue
            r = self.set_stop_loss(code, int(sl), qtys[code])
            if not self.live:
                placed.append(code)  # DRY-RUN: rencana tercatat, tak terkirim
                continue
            if not (r.get("errors") or r.get("error")):
                placed.append(code)
                self.log(f"SL reconcile {code}: pasang trig={int(sl)} qty={qtys[code]}")
            else:
                skipped.append(f"{code}(err {str(r)[:80]})")
                missing.append(code)
                self.log(f"SL reconcile {code}: GAGAL trig={int(sl)} qty={qtys[code]}: {str(r)[:160]}")
        return placed, missing, skipped

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
                # ditandai di scan (harga < MIN_PRICE) — jangan dibeli
                if r.get("price_skip"):
                    continue
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
                # beli DI ASK (persis protraderbot: order di offer side) — fallback last
                ask = self.best_ask(code)
                if ask:
                    self.log(f"  beli DI ASK {code}: ask {ask} (last {price})")
                    price = int(ask)
                # filter harga minimum (backstop): hanya beli saham harga >= MIN_PRICE
                # (price_skip di scan pakai ind.last; di sini pakai harga beli riil ask/last)
                if MIN_PRICE > 0 and price < MIN_PRICE:
                    self.log(f"[SKIP] {code} harga {price} < MIN_PRICE({MIN_PRICE}) "
                             f"— filter fundamental (beli hanya harga >= {MIN_PRICE})")
                    continue
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
                # guard akumulasi + PARTIAL SIZING: total semua order <= cash
                # (anti over-leverage!) — kalau sizing gede tapi cash kurang,
                # turunkan lot ke nilai TERDEKAT yang muat (>= 1 lot)
                if cash_left is not None:
                    val = qty_lot * 100 * price
                    if val > cash_left:
                        afford = int(cash_left // (100 * price))
                        if afford >= 1:
                            self.log(f"  partial {code}: sizing {qty_lot}lot Rp{val:,.0f} > cash "
                                     f"Rp{cash_left:,.0f} -> turun ke {afford}lot Rp{afford*100*price:,.0f}")
                            qty_lot = afford
                            val = qty_lot * 100 * price
                        else:
                            self.log(f"[SKIP] {code} min 1 lot Rp{100*price:,.0f} > sisa cash Rp{cash_left:,.0f}")
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
                # FLIP off -> sinyal SHORT TIDAK dieksekusi (exit hanya TP)
                if not FLIP:
                    self.log(f"[SKIP] {code} sinyal SHORT tapi FLIP off — exit hanya TP (fl>0.5% & close<SL)")
                    continue
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
                print(f"[{time.strftime('%H:%M:%S')}]  {code}: {d.get('current')} ({chg:+g}) O:{d.get('open')} "
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
_trade_ts = {"t": 0}   # timestamp trade token terakhir di-refresh (self-healing)


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
            # log per-saham ala protraderbot (i/N + action + trend + indikator)
            for i, r in enumerate(res, 1):
                ind = r.get("ind") or {}
                comm = ind.get("trend_comment") or ""
                act_disp = "SKIP-PRICE" if r.get("price_skip") else r["action"]
                bot.log(
                    f"[{i}/{len(res)}] {r['code']:<6} {act_disp:10s} [{comm}] "
                    f"ADX={ind.get('adx', 0):.1f} +DI={ind.get('pdi', 0):.1f} "
                    f"-DI={ind.get('mdi', 0):.1f} last={ind.get('last', 0):.0f} "
                    f"SMA20={ind.get('sma20', 0):.0f} SL={ind.get('sl', 0):.0f} "
                    f"pct={ind.get('adx_sma_pct', 0):.0f}% val={r.get('value', 0)/1e9:.2f}B")
            new_sig = []
            for r in res:
                if r["action"] == "HOLD":
                    continue
                if r.get("price_skip"):
                    # BUY terfilter harga — tampil di listing, TIDAK dieksekusi
                    bot.log(f"PRICE-SKIP {r['code']}: harga < MIN_PRICE({MIN_PRICE}) "
                            f"— tidak dibeli (kalau di holding tetap boleh dijual)")
                    continue
                key = (r["code"], r["action"])
                if last_state.get(key) != r["score"]:
                    last_state[key] = r["score"]
                    new_sig.append(r)
                    bot.log(f"SINYAL {r['action']} {r['code']} (skor {r['score']}): {r['reasons'][0]}")
            # HOLDING — log posisi BARIS TURUN + sinyal tiap posisi (SHORT = bakal jual)
            pos_res = []
            try:
                f = bot.flat_positions()
                rows = f["rows"]
                if rows:
                    live = bot._live_prices(
                        [r["code"] for r in rows],
                        {r["code"]: r["current"] for r in rows})
                    bot.log(f"HOLDING ({len(rows)}) — flat {f['total_flat']:+,.0f}:")
                    for i, r in enumerate(rows, 1):
                        try:
                            sig = bot.signal(r["code"], interval)
                            act = sig["action"]
                            if act != "HOLD":
                                pos_res.append(sig)
                        except Exception:
                            act = "?"
                        # harga LIVE PMP (flat_positions API Profits bisa telat)
                        cur = live.get(r["code"], r["current"])
                        # badge sinyal: SHORT (exit long) &/atau TP (floating profit)
                        flat_pct = ((cur - r["avg"]) / r["avg"] * 100) if r["avg"] else 0
                        flat_val = round((cur - r["avg"]) * r["qty"])
                        badges = [b for b in [act, "TP" if flat_pct > TP_PCT else None] if b]
                        badge = "+".join(badges) if badges else "-"
                        bot.log(f"  [{i}/{len(rows)}] {r['code']:<6} {max(r['qty'] // 100, 1):>4}lot "
                                f"avg{r['avg']:.0f} cur{cur:.0f} {flat_val:+,.0f} [{badge}]")
                else:
                    bot.log("HOLDING: 0 posisi")
            except Exception as e:
                bot.log(f"holding log error: {e}")
            # CASH — sisa cash real tiap cycle (biar tahu kondisi uang)
            try:
                bal = bot.get_balance()
                cash = (bal.get("data") or {}).get("cash")
                if cash is not None:
                    bot.log(f"CASH: Rp{cash:,.0f}")
            except Exception as e:
                bot.log(f"cash log error: {e}")
            # EKSEKUSI: sinyal top-15 + sinyal posisi (SHORT posisi = EXIT LONG otomatis)
            if auto_execute:
                act = [r for r in res if r["action"] != "HOLD"] + pos_res
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
                exits = bot.check_exit(tp_pct=TP_PCT,
                                       dc_mult=DONCHIAN_MULTIPLE,
                                       dc_per=DONCHIAN_PERIOD)
                if exits:
                    for e in exits:
                        bot.log(f"EXIT TP {e['code']}: +{e['flat_pct']}% (avg {e['avg']:.0f} -> {e['price']:.0f}, sl {e['sl']})")
                    if auto_execute:
                        plans = bot.execute_exits(exits, live=bot.live)
                        if plans:
                            bot.log(f"EXIT ORDER PLAN ({len(plans)}): " + ", ".join(
                                f"SELL {p['symbol']} {p['qty_lot']}lot @{p['price']}" for p in plans))
            except Exception as e:
                bot.log(f"exit check error: {e}")
            # RECONCILE SL — auto-pasang SL utk posisi yang masih belum ber-SL
            # (biar tak ada holding 'yatim'. skip yg sudah ber-SL & yg SL>=current)
            if auto_execute:
                try:
                    placed, missing, skipped = bot.reconcile_sl()
                    if placed or missing:
                        bot.log(f"RECONCILE SL: placed={placed} "
                                f"missing={missing} skipped={skipped}")
                except Exception as e:
                    bot.log(f"reconcile sl error: {e}")
            if not new_sig:
                bot.log(f"scan ok ({len(res)} saham, tidak ada sinyal baru)")
        except Exception as e:
            bot.log(f"loop error: {e}")
        _t.sleep(max(cycle_minutes * 60, 10))


def _pid_alive(pid):
    """Cek proses hidup (cross-platform). Windows: tasklist /FI."""
    import os as _os
    if _os.name == "nt":
        out = _os.popen(f"tasklist /FI \"PID eq {pid}\"").read()
        return str(pid) in out and "python" in out.lower()
    try:
        _os.kill(pid, 0)  # sinyal 0 = cek hidup
        return True
    except OSError:
        return False


def _single_instance_lock():
    """Cegah 2 bot jalan bersamaan (RACE CONDITION -> double order -> cash minus!).

    Lock file berisi PID, dibuat ATOMIK (O_EXCL) — 2 proses yang start di
    detik yang sama TIDAK bisa dua-duanya lolos (insiden 2026-08-12: 2
    profitsbot start bareng, lock lama tidak atomic -> dua-duanya jalan).
    Lock stale (PID mati) dibersihkan otomatis.
    """
    import os as _os
    lock = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "bot.lock")
    try:
        for _attempt in (1, 2):
            try:
                fd = _os.open(lock, _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
                _os.write(fd, str(_os.getpid()).encode())
                _os.close(fd)
                return True, lock
            except FileExistsError:
                try:
                    old_pid = int(open(lock).read().strip() or 0)
                except Exception:
                    old_pid = 0
                if old_pid and _pid_alive(old_pid):
                    return False, f"bot lain masih jalan (PID {old_pid})"
                try:
                    _os.remove(lock)  # stale (PID mati) — bersihkan
                except Exception:
                    pass
        return False, "lock bermasalah — hapus bot.lock manual lalu start ulang"
    except Exception:
        return True, lock  # fail-open: jangan blokir kalau lock error aneh


def main():
    import sys as _sys
    args = _sys.argv[1:]
    ok, lock = _single_instance_lock()
    if not ok:
        print(f"[{time.strftime('%H:%M:%S')}] TOLAK start: {lock} — stop dulu atau kill proses itu, lalu coba lagi!")
        print(f"[{time.strftime('%H:%M:%S')}] (2 bot jalan bersamaan = double order — insiden cash minus 2026-08-12)")
        return
    try:
        _main(args)
    finally:
        import os as _os
        try:
            if lock and _os.path.exists(lock):
                _os.remove(lock)
        except Exception:
            pass


def _main(args):
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
    auto_execute = live  # nontrade = scan&log; trade = eksekusi real (1 kontrol saja)
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
    if MIN_PRICE > 0:
        print(f"[{time.strftime('%H:%M:%S')}] [FILTER] MIN_PRICE={MIN_PRICE} aktif — HANYA beli saham harga >= {MIN_PRICE} (jual/exit bebas filter)")
    if USE_RSI_FILTER:
        print(f"[{time.strftime('%H:%M:%S')}] [FILTER] USE_RSI_FILTER=1 aktif — BUY long HANYA RSI>{RSI_BUY_MIN:.0f}, SHORT/FLIP HANYA RSI<{RSI_SELL_MAX:.0f} (paritas EA Basis_ADX_RSI)")
    if live:
        print(f"[{time.strftime('%H:%M:%S')}] !! TRADE MODE — order akan dikirim beneran !!")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] [NONTRADE/DRY-RUN] scan & log saja, tidak ada order dikirim.")
    if loop:
        run_loop(bot, cycle_minutes=cycle, interval=interval, auto_execute=auto_execute)
        return
    bot.run_once(symbols)
    if not live:
        print(f"\n[{time.strftime('%H:%M:%S')}] [DRY-RUN] Tidak ada order dikirim. Untuk live: python profits_bot.py --live")


if __name__ == "__main__":
    main()
