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

## Auth
- Header: `Authorization: Bearer <accessToken>` (token dari Svelte store `ze.accessToken`)
- Ada mekanisme refresh token (`refreshUnavailable` flag).
- Content-Type: application/json (FormData utk upload).

## Fitur trading (path API, template literal)
```
/portfolio/order/<id>/cancel            cancel order
/portfolio/exercise/<id>[/cancel]       exercise rights
/portfolio/stock/<code>/haircut         haircut
/automation/conditionalOrder/<id>       conditional order
/automation/stoploss/<id>  takeProfit/<id>  trailingStop/<id>
/automation/<id>/cancel   /automation/cancelAll
/catalog/order-queue/<x>[/<y>]          antrian order
/catalog/company/<code>[/profile|/price|/order-book]
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
`C:\Users\satri\OneDrive\Documents\PROFITS\`: `configuration/` (userdata.ini, rsatriyopranoto-config.xml), `log/profits.log`, `updates/ServerController.application`, `workspaces/`.

## Obfuscation status
- Backend Rust = native (no decompile bersih — cuma Ghidra/IDA, susah).
- Frontend JS = **minified** (Vite standard) — readable tapi nama pendek; TIDAK di-obfuscate sengaja, TIDAK di-encrypt. Asset path string kebaca di binary tapi blob data Tauri format-nya ribet → pakai CDP dump (jauh lebih mudah).

## Tools & file di repo ini
- `cdp_list.py`, `cdp_dump.py`, `cdp_fetch.py` — dump CDP (butuh `websocket-client`; pakai venv protraderbot: `/c/Users/satri/code/protraderbot/.venv/Scripts/python.exe`)
- `probe_pe*.py`, `probe_taubndl.py`, `probe_assets*.py`, `probe_exp.py`, `probe_extract.py`, `probe_final.py`, `probe_vite.py` — analisis PE/bundle (hasil: NSIS/Inno+UPX installer, app asli Tauri)
- `dump/index_rendered.html` (187KB), `dump/index-BUMcGDRC.js` (1,5MB), `dump/index-CbZLwW9f.css` (131KB)

## Catatan
- profits.exe di Downloads/ (6,3MB) = NSIS installer; profits-setup.exe (104MB) = Inno Setup + UPX — keduanya BUKAN app.
- App single-instance-ish: kalau instance lama masih jalan, instance baru exit diam-diam (exit 0).
- Jangan commit kredensial user (userdata.ini bisa berisi data akun).
