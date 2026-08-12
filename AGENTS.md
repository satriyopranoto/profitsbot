# profitsbot — AGENTS.md

Reverse-engineering `profits.exe` — aplikasi trading **"Profits" (Phintraco Sekuritas, profits.co.id)**.
Binary: `C:\Users\satri\AppData\Local\Profits\profits.exe` (19,7MB, x64, build `8c9ca94.2026-08-10`).

## Tech stack (TERBUKTI dari PE header + strings + dump CDP)
- **Tauri v2 (Rust)** — backend native x64. Bukti: section `.taubndl`, 310x string "tauri", 1149x "cargo", 278x "rustc".
- **Frontend: Svelte + Tailwind + ChartJS** (Vite build — hashed assets `index-BUMcGDRC.js`, class `svelte-*`). BUKAN React!
- **WebView2 (Chromium/Edge)** renderer — `msedgewebview2.exe` child processes.
- ⚠️ Versi lama (log s/d 5-Agu-2026) = **Python** (`[INFO][MODULE::funcName]` logging style). Di-rewrite ke Rust/Tauri tanggal 10-Agu — kemungkinan hardening setelah investigasi Frida/mitm 29-Jul.

## Cara dump frontend (CDP WebView2) — TERBUKTI JALAN
```bash
export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222 --remote-allow-origins=*"
cd /c/Users/satri/AppData/Local/Profits && ./profits.exe &
# tunggu ~5s, lalu:
curl -s http://localhost:9222/json            # daftar target (tauri.localhost)
python cdp_dump.py   # HTML penuh -> dump/index_rendered.html
python cdp_fetch.py  # fetch semua JS/CSS dari dalam halaman -> dump/
```
PENTING: `--remote-allow-origins=*` WAJIB (tanpa itu WebSocket 403). Tanpa env args app JALAN normal; dengan env args kadang exit diam-diam — kill sisa msedgewebview2 dulu kalau perlu.

## Endpoint (dari JS bundle)
- API: `https://next-dev.profits.co.id/api` (ENV_MODE="prod" di bundle!)
- Chart: `https://next-dev.profits.co.id/chart` + `https://next-dev.profits.co.id/api/chart`
- WS streaming: `wss://stream.profits.co.id` (storage keys: `app-jid`, `app-tjid`)
- Update app: `https://assets.profits.co.id/download/profits/latest.json`
- Referral/daftar: `https://daftar.profits.co.id/` ; share via `api.whatsapp.com/send`

## AUTH (LENGKAP)
```
POST /identity/login            login utama (user+password) -> {token:{accessToken, refreshToken, accessExpired}}
POST /identity/refresh          refresh accessToken
POST /identity/trade/login      login TRADING pakai PIN {pin}
POST /identity/trade/refresh    refresh trade token ({refreshToken})
POST /identity/socket-token/market | /trade   token utk WS
POST /identity/logout
GET  /identity/user-detail
POST /identity/change-password | /identity/change-pin
POST /identity/forgot-password/request|validate|reset
POST /identity/bond/token
```
- Header: `Authorization: Bearer <accessToken>` (token dari Svelte store `ze.accessToken`)
- ⚠️ LOGIN (TERVERIFIKASI via capture request asli + crypto-js):
  - password DIENKRIPSI: `CryptoJS.AES.encrypt(password, "1231231231231231")` =
    OpenSSL salted (prefix `U2FsdGVkX1`): salt 8B acak + AES-256-CBC,
    KDF EvpKDF `D_i = MD5(D_{i-1} || password || salt)`, blok terakhir saja
    (bukan akumulasi; urutan password DULU baru salt — beda dari asumsi awal!)
  - header `authorization: "Bearer"` TANPA spasi saat belum ada token
    (`"Bearer <token>"` kalau ada token) — 400 "wrong" kalau spasi!
  - `X-APP-PLATFORM: "windows"` di desktop (dari Tauri OS plugin), bukan "web"
  - login response: `{data:{user:{...}, token:{accessToken, refreshToken, accessExpired}}}`
    (token di data.token!)
- Auto-refresh timer: `(accessExpired - 30s)` → panggil refresh dgn refreshToken.
- Trade session: store `ze.tradeSession` (setTrade dari `/identity/trade/login`).
- ⚠️ PORTFOLIO BUTUH TRADE TOKEN: `/portfolio/*` dipanggil dgn `auth: ze.tradeAccess`
  (token dari `/identity/trade/login` {pin}) — accessToken biasa -> 401 UNAUTHORIZED.
  Respons trade/login: `{data:{token:{accessToken,...}}}` (atau data langsung) — TERVERIFIKASI.
- TERVERIFIKASI: /portfolio/balance -> {totalCash, cash, maxLimit, potensial, multiplier, rdnCash};
  /portfolio/stock -> [{code, available, total, avgPrice, price, company{...}}];
  /portfolio/order -> [order aktif].

## ORDER (LENGKAP)
```
GET  /portfolio/order                list order
GET  /portfolio/order/done           history order
POST /portfolio/order/done/export    export
POST /portfolio/order                CREATE ORDER (header X-APP-FORM)
PUT  /portfolio/order/<id>           update
PUT  /portfolio/order/batch          update batch
POST /portfolio/order/<id>/cancel    cancel
```
Payload createOrder (TERVERIFIKASI LIVE 2026-08-12):
```js
{qty, gtc: bool, isBuy: bool, split: {count} | 0, useLimit: bool,
 price, code: <kode saham>, orderType: "limit"|"market"|"trailing-stop",
 expire: "day"}   // WAJIB! tanpa expire -> 400 {"errors":{"expire":[{"tag":"required"}]}}
```
- ⚠️⚠️⚠️ qty = dalam LOT (1 lot = 100 lembar) utk BUY & SELL — TERVERIFIKASI LIVE:
  qty=1 -> total = price*100. Kirim qty=100 (anggap lembar) = 100 LOT!
  (buy ANTM 100 -> total 30,9jt — LEVERAGE implicit kalau > cash tapi <= maxLimit!)
  SELL qty=100 (100 lot) -> 400 "insufficient balance" (posisi 31 lot).
- X-APP-FORM: "ro" (regular order, buy & sell) — "so" juga diterima utk sell.
- Buy/sell limit di luar jam pasar = masuk antrian PENDING, eksekusi saat market buka.
- Respons sukses: `{data: <orderUUID>}`; order terlihat di GET /portfolio/order
  (status PENDING -> WITHDRAWN kalau di-cancel; cancel: POST /portfolio/order/<id>/cancel
  -> {data: <uuid>}).
- ⚠️ SL/automation butuh POSISI: POST /automation/stoploss utk saham yang BELUM
  dimiliki -> 400 "stock not found" (SL hanya utk saham yang sudah jadi posisi).
- `X-APP-FORM`: "ro" (regular order) / "so" (sell order?) — dari UI.
- ⚠️⚠️ CASH ONLY (instruksi USER): JANGAN PERNAH leverage/margin! Payload order
  desktop TIDAK punya field leverage (fitur "Leverage 2x" khusus app MOBILE —
  bundle desktop cuma 1x string "Leverage" di UI). Order API = cash/regular.
  Guard di bot: nilai order WAJIB <= balance.cash (totalCash 15,8jt), BUKAN maxLimit.
- STOP LOSS (TERVERIFIKASI LIVE 2026-08-12):
  POST /automation/stoploss {id:"", code, triggerPrice, executeQty, executePriceMode,
    customExecutePrice:0, expireDate} -> {data: uuid} ACTIVE. BUTUH POSISI SAHAM.
  CANCEL: POST /automation/stoploss/<id>/cancel -> {data: uuid} (type WAJIB di URL —
  /automation/<id>/cancel -> 404!). /automation/stoploss/cancelAll utk semua.
  executePriceMode: "LAST_PRICE" (terverifikasi dari SL user) — bukan "market"!
  expireDate ISO; 90 hari = protokol IDX (≤90 hari).

## WS streaming (wss://stream.profits.co.id — TERVERIFIKASI)
- URL: `wss://stream.profits.co.id/market?key=<socket-token>` (market) /
  `.../trade?key=` (portfolio/order) — PATH WAJIB, tanpa path server balas "Hello"!
- Subscribe: `sub|<market>|<channel>|<symbols>` (contoh `sub|market|price|BBCA`)
  - channel: price / order_book / trade (batch `BBCA,BBRI`) / status (`TRADE`) / alarm
- Unsubscribe: `unsub|...` format sama
- Heartbeat DUA ARAH: server kirim `"ping"` -> WAJIB balas `"pong"` (kalau tidak koneksi di-drop);
  app juga kirim `"ping"` tiap 20s -> server balas `"pong"`
- Perlu token dari `/identity/socket-token/market` & `/trade` (storage: `app-jid`, `app-tjid`)
- Server maintenance 22:00-00:05 WIB -> data feed kosong (WS tetap connect, tapi nol pesan)

## Fitur trading (path API, template literal)
```
/portfolio/order/<id>/cancel            cancel order
/portfolio/exercise/<id>[/cancel]       exercise rights
/portfolio/stock/<code>/haircut         haircut
/automation/conditionalOrder/<id>       conditional order
/automation/stoploss/<id>  takeProfit/<id>  trailingStop/<id>
/automation/<id>/cancel   /automation/cancelAll
/catalog/order-queue/<x>[/<y>]          antrian order
/catalog/company/<code>[/profile|/price|/order-book]  ← HARGA REST TERVERIFIKASI:
  GET /catalog/company/<CODE>/price -> {current, prev, change, open, high, low} — jalan 24/7
  (data sesi masih ada sampai di-clear 08:00 WIB; WS hanya kirim saat ada perubahan harga)
  GET /trade-book/trade-book/<CODE>/price -> market depth (bid/offer per price level)
- DATA PASAR (TERVERIFIKASI):
  GET /trade-book/trade-book/top-stocks -> [{buy:{code,curr,change,val,freq,lot,avg}, sell:{...}}]
    (50 item; sort val -> TOP VALUES 15)
  GET /trade-book/chart/<CODE>/price?cursor=<ts> -> [{time:'HH:MM', price}] intraday per menit
    (sesi terakhir ~335 titik — utk indikator intraday)
  GET /trade-book/trade-book/<CODE>/chart|time -> depth/bid-offer per waktu
  Flat: dari /portfolio/stock (avgPrice vs price) x total
/trade-book/trade-book/<code>/price|time|chart
/trade-book/mover/<x>
/workspace/watchlist/<id>[/rename]      watchlist
/workspace/settings/trade-audio/<id>[/reset]
/alert/alarm/<id>                       alert
/analytics/broker/*, /analytics/financial/<code>/*, /analytics/pivot/<x>,
/analytics/trend-meter/<x>, /analytics/research/*, /analytics/financial/<code>/market-info
```

## Tauri plugins terdeteksi (invoke)
`plugin:http|fetch`, `plugin:fs|*`, `plugin:dialog|save`, `plugin:event|*`, `plugin:image|*`, `plugin:opener|open_*`, `plugin:process|restart_*`

## Struktur data lokal (Dokumen)
`C:\Users\satri\OneDrive\Documents\PROFITS\`: `configuration/` (userdata.ini, [user]-config.xml), `log/profits.log`, `updates/ServerController.application`, `workspaces/`.

## Obfuscation status
- Backend Rust = native (no decompile bersih — cuma Ghidra/IDA, susah).
- Frontend JS = **minified** (Vite standard) — readable tapi nama pendek; TIDAK di-obfuscate sengaja, TIDAK di-encrypt. Asset path string kebaca di binary tapi blob data Tauri format-nya ribet → pakai CDP dump (jauh lebih mudah).

## ARSITEKTUR DATA (fallback chain real-time)
- Bot Profits tanya harga real-time -> bot PROTRADER (http://127.0.0.1:8777/price/<CODE>)
  — protraderbot/bot/api_server.py (PMP real-time: bid/ask/last) — timeout 8s.
- Kalau bot protrader mati/nggak jawab -> fallback YAHOO .JK (delay ~10 menit).
- `profits_bot.real_time_price(code)` -> {source: protrader|yahoo, bid, ask, last, vol, ts}.
- Data indikator OHLC tetap dari Yahoo (delay OK utk MA/ADX 15m/harian).

## PARAMETER (env — analog protraderbot BOT_MODE/dll)
- PROFITS_BOT_MODE=nontrade|trade — nontrade = DRY-RUN scan/log (default); trade = order real.
  CLI: --nontrade/--dry-run | --trade/--live (--live alias lama tetap ada).
- PROFITS_ADX_CROSS (15) & PROFITS_ADX_TREND (25) — threshold ADX utk sinyal.
- PROFITS_SL_DONCHIAN_PERIOD (20) — lookback Donchian utk SL (sl_donchian_plan:
  trigger = lower - 1 tick; log setelah BUY; SETELAH posisi terisi baru bisa dipasang).
- PROFITS_FLIP (0/1) — 1 = SELL sinyal tutup posisi PENUH (avail/100 lot); 0 = jual 1 lot.

## LOOP / RUN (main)
- `python profits_bot.py --loop [--cycle 3] [--interval 15m] [--execute] [--live]`
- Config env: PROFITS_CYCLE_MINUTES (3), PROFITS_SCAN_INTERVAL (15m),
  PROFITS_AUTO_EXECUTE (0/1), PROFITS_MARKET_OPEN/CLOSE (09:00/15:30 WIB, weekday).
- Loop: scan top values 15 tiap cycle saat market buka; lapor SINYAL BARU (dedup
  per code+action+score — nggak spam); --execute -> execute_signals (DRY-RUN).
- market_open() = weekday & jam WIB dalam range.

## STRATEGI SINYAL (terverifikasi 2026-08-12)
- `signal(code, interval)` — OHLC Yahoo -> ADX series (+DI/-DI/ADX Wilder) + RSI + SMA20:
  BUY = +DI cross ABOVE -DI (ADX>=15) ATAU +DI>-DI & ADX>=25; filter RSI<75 & close>SMA20
  SELL = kebalikannya (-DI cross/+DI); filter RSI>25 & close<SMA20
- `scan_signals(codes=None)` — default scan TOP VALUES 15 (top-stocks) — ~2s utk 15 saham
- `execute_signals(results, min_score=1, live=False)` — BUY: skip kalau sudah punya posisi
  (anti-numpuk), harga real-time (fallback chain), GUARD AKUMULASI cash (total plan <= cash);
  SELL: skip kalau tidak punya posisi, jual 1 lot. DRY-RUN default, --live eksplisit.
- Contoh scan 15m: BUY JECX/MEDC/MMIX; SELL ANTM/PTBA (bearish kuat).

## Indikator (indicators.py + OHLC Yahoo .JK)
- SMA/EMA/RSI/MACD/Bollinger/Donchian/ATR — dari close.
- ADX LENGKAP (+DI/-DI/ADX, Wilder) dari OHLC asli — adx_full(h,l,c,n).
- OHLC ASLI = Yahoo Finance: https://query1.finance.yahoo.com/v8/finance/chart/<CODE>.JK
  ?range=<1d|5d|3mo|1y>&interval=<1m|5m|15m|1d> — TANPA AUTH!
  -> 15m = 111-145 titik (5 hari), 1d = 244 titik (1 tahun). TERVERIFIKASI.
  (chart Profits = TradingView iframe delay & API Profits cuma close per-menit 335 titik)
- `profits_bot.fetch_ohlc(code, interval, range)` & `indicator_snapshot(code)`.
- Contoh (15m): ANTM +DI 12.95/-DI 25.46/ADX 28.92 DOWN; PTBA ADX 63.15 DOWN kuat.

## Tools & file di repo ini
- `cdp_list.py`, `cdp_dump.py`, `cdp_fetch.py` — dump CDP (butuh `websocket-client`; pakai venv protraderbot: `/c/Users/satri/code/protraderbot/.venv/Scripts/python.exe`)
- `probe_pe*.py`, `probe_taubndl.py`, `probe_assets*.py`, `probe_exp.py`, `probe_extract.py`, `probe_final.py`, `probe_vite.py` — analisis PE/bundle (hasil: NSIS/Inno+UPX installer, app asli Tauri)
- `dump/index_rendered.html` (187KB), `dump/index-BUMcGDRC.js` (1,5MB), `dump/index-CbZLwW9f.css` (131KB)

## Catatan
- ⏰ TEST ORDER LIVE = MANUAL oleh user, pas jam pasar (09:00 WIB) — jangan auto-start/
  jangan pasang cron. Jalankan: `python profits_bot.py --symbols <CODE> --live` (1 lot dulu).
- profits.exe di Downloads/ (6,3MB) = NSIS installer; profits-setup.exe (104MB) = Inno Setup + UPX — keduanya BUKAN app.
- App single-instance-ish: kalau instance lama masih jalan, instance baru exit diam-diam (exit 0).
- Jangan commit kredensial user (userdata.ini bisa berisi data akun).
