# profitsbot — RE / Analisis profits.exe (Phintraco "Profits")

Analisis binary `profits.exe` (AppData/Local/Profits, 19.7MB, build 8c9ca94.2026-08-10).

## Tech stack (terbukti dari PE header + strings)
- **Tauri v2 (Rust)** — backend native x64 (section .taubndl, 310x "tauri", 1149x "cargo")
- **Frontend: Svelte + Tailwind + ChartJS** (Vite build, hashed assets, 1.5MB JS bundle)
- **WebView2 / Chromium** renderer (v8, webview2 hits)
- Versi lama (log s/d 5-Agu): **Python** — di-rewrite ke Rust/Tauri 10-Agu

## Frontend (di-dump via WebView2 remote-debug CDP)
- `dump/index_rendered.html` — 187KB HTML render
- `dump/index-BUMcGDRC.js` — 1.5MB JS bundle (minified)
- `dump/index-CbZLwW9f.css` — 131KB

## Endpoint (dari bundle)
- API: `https://next-dev.profits.co.id/api` (ENV_MODE=prod!)
- Chart: `https://next-dev.profits.co.id/chart` + `/api/chart`
- WS streaming: `wss://stream.profits.co.id`
- Update: `https://assets.profits.co.id/download/profits/latest.json`
- Daftar/referral: `https://daftar.profits.co.id/`

## Auth
- `Authorization: Bearer <accessToken>` — token dari Svelte store (`ze.accessToken`)
- Ada mekanisme refresh token

## Fitur trading (path dari bundle)
- `/portfolio/order/<id>/cancel` — cancel order
- `/automation/conditionalOrder|stoploss|takeProfit|trailingStop` + cancelAll — automation
- `/catalog/order-queue`, `/catalog/company/<code>/order-book|price`
- `/trade-book/trade-book/<code>/price|time|chart`
- `/workspace/watchlist`, `/portfolio/exercise`, `/portfolio/stock/<code>/haircut`
- `/alert/alarm/<id>`, `/analytics/*` (riset)

## Cara dump ulang
1. `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222 --remote-allow-origins=*" ./profits.exe`
2. `python cdp_fetch.py` (butuh websocket-client)
