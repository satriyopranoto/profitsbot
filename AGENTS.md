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
- OHLC indikator -> bot PROTRADER juga: `fetch_ohlc(code)` = GET http://127.0.0.1:8777/chart/<CODE>
  ?resolution=<map>&countback=2000&days_back=10 -> {code, data:[{t,o,h,l,c,v}], bars}
  (OHLC ChartCloud POEMS real-time — SUMBER UTAMA). Yahoo jadi fallback TERAKHIR kalau
  api_server mati. Satu sumber = sinyal konsisten dgn protraderbot (TERVERIFIKASI 2026-08-19:
  ISAT 147 bars, ADX 28.5/pct 24% ~= protraderbot 25.3/23%; sebelum fix Yahoo melenceng 3%
  -> 'Uptrend Kuat 69%' PALSU). ⚠️ api_server 8777 WAJIB jalan utk data akurat.

## CONFIG LENGKAP (env — analog .env protraderbot) — TERVERIFIKASI
- CHART: TIMEFRAME sinyal dikontrol **PROFITS_SCAN_INTERVAL** (mis. `30m`; source-of-truth,
  di-map ke resolution TradingView via `res_map` di `fetch_ohlc`). `PROFITS_CHART_RESOLUTION` &
  `PROFITS_CHART_COUNTBACK` **SUDAH DIHAPUS 2026-08-26** (variabel nganggur — countback api_server
  = 2000 hardcoded; jangan dipakai lagi). Sumber utama = ChartCloud POEMS via api_server /chart
  (147 bar/10 hari utk 15m); Yahoo fallback: 1m~390 bar, 15m~145 bar/5d, 1d~247 bar/1y;
  3/45/120/240m → interval terdekat).
- INDIKATOR: PROFITS_ADX_PERIOD (14), PROFITS_ADX_THRESHOLD (20), PROFITS_ADX_CROSS (15),
  PROFITS_DONCHIAN_PERIOD (10 — SL lookback = 2.8x = 28 bar),
  PROFITS_BOLLINGER_PERIOD (20), PROFITS_BOLLINGER_STD (2).
- WATCHLIST/FILTER: PROFITS_TOP_VALUES (15), PROFITS_FILTER_DISCRETE (1),
  PROFITS_MAX_FLAT_PCT (50) — % bar flat > max -> HOLD "DISCRETE".
- MODE: PROFITS_BOT_MODE (nontrade|trade), PROFITS_TRADE_LOT (0 = sizing), PROFITS_TEST_SYMBOL
  (test cycle langsung di saham itu), PROFITS_USE_FLIP / PROFITS_FLIP (1), PROFITS_CYCLE_MINUTES (3).
- SIZING (persis protraderbot sizing.py): TRADE_LOT=0 ->
  risk_amount = CAPITAL * RISK_PCT/100; lot = floor(risk_amount / (|price-sl| * 100)).
  ORDER_VALUE=0 -> tanpa cap (guard akumulasi cash yg batasi); >0 -> cap nilai/order.
  PROFITS_CAPITAL (100jt), PROFITS_RISK_PCT (1.0).
- Alias: PROFITS_SL_DONCHIAN_PERIOD (= DONCHIAN_PERIOD default).
- Terverifikasi: JECX 99 lot (risk 1jt / |1320-1219|*100); SL 1219 (lookback 28);
  MEDC di-skip (Rp29jt > sisa cash).

## PARAMETER (env — analog protraderbot BOT_MODE/dll)
- PROFITS_BOT_MODE=nontrade|trade — nontrade = DRY-RUN scan/log (default); trade = order real.
  CLI: --nontrade/--dry-run | --trade/--live (--live alias lama tetap ada).
- PROFITS_ADX_CROSS (15) & PROFITS_ADX_TREND (20 — USER: 20) — threshold ADX utk sinyal.
- PROFITS_SL_DONCHIAN_PERIOD (20) — lookback Donchian utk SL (sl_donchian_plan:
  trigger = lower - 1 tick; log setelah BUY; SETELAH posisi terisi baru bisa dipasang).
- PROFITS_FLIP (1 — USER: true) — SELL sinyal tutup posisi PENUH (avail/100 lot); 0 = jual 1 lot.

## LOOP / RUN (main)
- `python profits_bot.py --loop [--cycle 3] [--interval 15m] [--execute] [--live]`
- EXIT CHECK (check_exit): posisi dgn floating profit > PROFITS_TP_PCT (0.5%)
  -> SELL (jual available) — di-loop tiap cycle; execute kalau auto_execute/live.
- - Config env: PROFITS_CYCLE_MINUTES (3), PROFITS_SCAN_INTERVAL (15m),
  PROFITS_MARKET_HOURS (0 = 24 jam testing; 1 = jam bursa),
  PROFITS_MARKET_OPEN/CLOSE (09:00/15:30 WIB, weekday).
- Loop: scan top values 15 tiap cycle saat market buka; lapor SINYAL BARU (dedup
  per code+action+score — nggak spam); --execute -> execute_signals (DRY-RUN).
- market_open() = weekday & jam WIB dalam range.

## STRATEGI SINYAL (terverifikasi 2026-08-12)
- `signal(code, interval)` — OHLC Yahoo -> ADX series (+DI/-DI/ADX Wilder) + RSI + SMA20 + adx_sma_pct:
  BUY  = low>SL(Donchian 2.8x) & close>SMA20 & ADX>ADX_THRESHOLD & ADX naik(5)
         & +DI>-DI & +DI naik(5)   [strict >, bukan cross, bukan >=]
  SHORT = high<SL & close<SMA20 & ADX>ADX_THRESHOLD & ADX naik(5)
         & -DI>+DI & -DI naik(5)   [sinyal bearish = pemicu EXIT LONG — IDX cash ga bisa short]
- **⚡ SWITCH SL (2026-09-02, paritas EA/protraderbot/usbot)** — SL di `signal()`
  memakai **switch** (`sl = ac==1 ? s : r`, `indicators.donchian_sl_switch`), ac = arah
    Donchian-breakout terakhir (ffill). Saat regime DOWN (ac=-1) `sl` = **band ATAS** →
    `high<sl` mudah → sinyal SHORT/FLIP **lebih awal**. Flip TETAP HANYA kalau rumus short
    PENUH terpenuhi (bukan semata regime change). **Ini fix propagasi error**: profitsbot
    dulu jadi acuan usbot yang ikut kena bug `sl` lower-fixed (usbot sudah di-fix dulu);
    sekarang profitsbot di-paritas-kan. Toggle `PROFITS_SWITCH_SL` (default 1 = selalu switch).
    Verifikasi (read-only): ANTM & INCO kini SHORT (sl=band-atas) yg sebelumnya HOLD; BBCA
    tetap BUY dgn SL lebi rapat (low-band). Profitsbot baca config saat START → restart wajib.
    - **check_exit (TP/trailing) paritas switch (2026-09-02)**: exit HOLD `close < SL` memakai
      `sl_donchian_switch` (paritas protraderbot donchian_sl) saat PROFITS_SWITCH_SL=1 → di
      regime DOWN sl = band ATAS → exit TP lebih awal; kalau PROFITS_SWITCH_SL=0 → LLV legacy.
      ⚠️ **Pasang SL ORDER tidak ikut switch** — `sl_donchian_price` (LLV) tetap dipakai utk
            SL-install (mass_sl_setup, set_stop_losses) karena stop harus DI BAWAH untuk long.
        **Prinsip SL (keputusan user, 2026-09-02):** SL-install utk LONG SELALU band bawah (LLV /
        Donchian lower) — saat buy (regime UP, `low>sl`) SL pasti DI BAWAH harga → stop valid & aktif.
        Switch SL HANYA utk deteksi sinyal & exit (signal/check_exit), BUKAN utk memasang SL. Kalau SL
        switch DI ATAS harga saat mau pasang = tanda buy TELAT / sudah berbalik → manual intervention.
- `scan_signals(codes=None)` — default scan TOP VALUES 15 (top-stocks, fallback SYMBOLS) — ~2s/15 saham;
  **transparansi scanner (2026-09-02)**: cetak sumber + daftar watchlist yg di-scan
  (`[SCAN] watchlist <N> saham dari top-stocks(Profits)/SYMBOLS fallback: CODE:V.B ...`)
  → bukti scan dari top-values, bukan "thin air". (Kalau N kecil, itu karena data
    `trade-book/top-stocks` Profits tipis di luar jam pasar — di-clear 08:00 WIB.)
    **⚠️ MERGE buy+sell + floor (2026-09-02):** endpoint `/top-stocks` memberi 50 item
    berisi PAIR `{buy, sell}` (sisi terpisah); `top_values()` kini baca KEDUA sisi
    (dedup per saham ambil val MAX — nilai transaksi matched, BUKAN dijumlah), bukan
    cuma `buy` (sebelumnya mover besar BBRI/CUAN/BMRI yg di sisi `sell` terlewat →
    scan cuma 1 dgn MIN_TOP_VAL=50B). Catatan: val API ~5x lebih kecil dari PMP/UI
    (bedadefinisi feed), & `MIN_TOP_VAL` disetel 15B utk ~30 saham.
    ranking persis stocktrade: sort (rekomendasi BUY3/SHORT2, adx_sma_pct, value) desc — TIDAK memfilter.
- `execute_signals(results, min_score=1, live=False)` — BUY: syarat uptrend kuat (adx_sma_pct>=35,
  default) + skip kalau sudah punya posisi (anti-numpuk), harga = BEST ASK (order-book, fallback last),
  GUARD AKUMULASI cash (total plan <= cash) + PARTIAL SIZING: kalau sizing
  gede tapi cash kurang -> lot diturunkan ke nilai TERDEKAT yang muat (>=1 lot),
  bukan skip total (mis. butuh 12jt, cash 9jt -> beli 9jt); SHORT: skip kalau tidak punya posisi,
  kalau punya = EXIT LONG (FLIP=1 penuh / 1 lot). DRY-RUN default, --live eksplisit.
- `check_exit(tp_pct, dc_mult=2.8, dc_per=10)` — SELL jika: floating_pct > PROFITS_TP_PCT (0.5%)
  **AND** close < SL DONCHIAN (LLV high/low asli, lookback dc_mult x dc_per) — kembali
  ke Strong klasik (backtest portfolio 2026-08-14: Strong+SL Donchian juara ID D1
  +875%/H1 +417% vs TP Basis; paritas EA Strong/protraderbot donchian_sl; revert dari
  commit c86280e; `sl_donchian_price()` baru). Trailing TP: profit > 0,5% BELUM dijual —
  baru jual kalau harga BALIK tembus SL Donchian. Jual DI BID (best bid — langsung kena,
  tidak ngantri). `sl_donchian_plan` tetap dipakai utk SL order, bukan exit.
- **BELI DI ASK / JUAL DI BID**: `order_book(code)` = GET /catalog/company/<CODE>/order-book
  -> {bids:[{price,...}], offers:[...]} — best bid = bids[0].price, best ask = offers[0].price.
- **SHORT (sinyal) vs SELL (exit long)**: SHORT = sinyal bearish -> pemicu EXIT LONG (jual posisi yg
  dipunya); SELL = tindakan exit long dari TP check. Guard cash HANYA utk BUY (SELL tidak diblokir!).
- **FLIP toggle** (`PROFITS_FLIP`, default 1): FLIP=1 -> exit = (fl>0.5% AND close<SL) **OR** sinyal
  SHORT (SHORT exit aktif, jual penuh); FLIP=0 -> SHORT di-SKIP, exit HANYA TP trailing. Nama lama
  PROFITS_USE_FLIP dihapus (jangan dipakai lagi).
- **⚠️ SL plan vs SL terpasang**: execute_signals BUY cuma LOG "SL plan CODE: trigger X" — automation
  stoploss TIDAK otomatis terpasang! Set manual via `set_stop_loss(code, trigger, qty_lot)` (POST
  /automation/stoploss, executePriceMode LAST_PRICE, expire +60 hari) — VERIFIKASI LIVE 2026-08-12:
  ISAT 2099 (960053f2), BREN 3269 (ab2d5d70), EXCL 2409 (e5e326b8), CUAN 674 (2c73806b).
- Contoh scan 15m: BUY JECX/MEDC/MMIX; SHORT ANTM/PTBA (bearish kuat).

## Loop & keselamatan (2026-08-12 — pelajaran mahal!)
- `run_loop`: scan top-15 (log per-saham ala protraderbot) -> HOLDING baris TURUN per posisi
  + badge sinyal [BUY]/[SHORT]/[TP] (TP = floating > TP_PCT) -> log CASH tiap cycle
  -> execute (top-15 + sinyal posisi lama — SHORT posisi = EXIT LONG otomatis) -> check_exit TP.
- **SINGLE-INSTANCE LOCK** (`bot.lock`, PID): bot kedua TOLAK start kalau ada bot hidup —
  WAJIB! Server Profits TIDAK kick 2 login (2 proses bisa order bersamaan!) — insiden
  2026-08-12: 2 bot racing -> CUAN 4+4 & BREN 17+17 double order -> cash MINUS -3,2jt.
- **PROFITS_BOT_MODE = satu-satunya kontrol**: nontrade (scan&log) | trade (eksekusi real).
  AUTO_EXECUTE SUDAH DIHAPUS (dulu bikin bingung). CLI --nontrade/--trade override .env.
- **JANGAN jalanin bot utk user** ("aku aja") — user yang start loop; asisten hanya verifikasi
  (tasklist/wmic/powershell Get-CimInstance utk cek proses python hidup).
- Partial sizing log: "partial CODE: sizing Xlot RpY > cash RpZ -> turun ke Wlot".
- Exit TP log: "EXIT TP CODE: +X% (avg A -> cur B)" lalu "jual DI BID CODE: bid B (last C)".

## Indikator (indicators.py + OHLC via api_server protrader)
- SMA/EMA/RSI/MACD/Bollinger/Donchian/ATR — dari close.
- ADX LENGKAP (+DI/-DI/ADX, Wilder) dari OHLC asli — adx_full(h,l,c,n).
- OHLC ASLI = ChartCloud POEMS via api_server protrader:
  GET http://127.0.0.1:8777/chart/<CODE>?resolution=<map>&countback=2000&days_back=10
  -> {code, data:[{t,o,h,l,c,v}], bars} — TANPA AUTH (service lokal).
  Map interval: 1m->1, 5m->5, 15m->15, 30m->30, 45m->45, 60m/1h->60, 1d/D->D.
  15m = 147 bar/10 hari. Yahoo jadi fallback TERAKHIR kalau service mati.
  (Sebelum 2026-08-19: OHLC murni Yahoo — kadang melenceng 3% dari bursa
  -> ADX & uptrend pct bisa PALSU; fix: fetch_ohlc ambil dari api_server dulu.)
- `profits_bot.fetch_ohlc(code, interval, range)` & `indicator_snapshot(code)`.
- Contoh (15m): ANTM +DI 12.95/-DI 25.46/ADX 28.92 DOWN; PTBA ADX 63.15 DOWN kuat.

## Tools & file di repo ini
- `cdp_list.py`, `cdp_dump.py`, `cdp_fetch.py` — dump CDP (butuh `websocket-client`; pakai venv protraderbot: `/c/Users/satri/code/protraderbot/.venv/Scripts/python.exe`)
- `probe_pe*.py`, `probe_taubndl.py`, `probe_assets*.py`, `probe_exp.py`, `probe_extract.py`, `probe_final.py`, `probe_vite.py` — analisis PE/bundle (hasil: NSIS/Inno+UPX installer, app asli Tauri)
- `dump/index_rendered.html` (187KB), `dump/index-BUMcGDRC.js` (1,5MB), `dump/index-CbZLwW9f.css` (131KB)
- `mass_sl_setup.py` — **UTILITY LIVE**: pasang SL Donchian utk SEMUA holding yg belum ber-SL. `--dry-run` = rencana saja (AMAN). Profitsbot TIDAK punya reconciliation SL otomatis => ada holding "yatim" tanpa SL (insiden 08-25: 4/10); utility ini menambal. SKIP yg sudah ber-SL & yg SL-nya tembus; qty=LOT (total//100). Manual override via `MANUAL` dict.
- `housekeep_sl_profitsbot.sh` — **UTILITY**: script housekeeping SL orphaned (dipanggil cron 16:15 workdays; mode agent + workdir repo; `python housekeep_sl.py`)

## Catatan
- ⏰ TEST ORDER LIVE = MANUAL oleh user, pas jam pasar (09:00 WIB) — jangan auto-start/
  jangan pasang cron. Jalankan: `python profits_bot.py --symbols <CODE> --live` (1 lot dulu).
- profits.exe di Downloads/ (6,3MB) = NSIS installer; profits-setup.exe (104MB) = Inno Setup + UPX — keduanya BUKAN app.
- App single-instance-ish: kalau instance lama masih jalan, instance baru exit diam-diam (exit 0).
- Jangan commit kredensial user (userdata.ini bisa berisi data akun).
