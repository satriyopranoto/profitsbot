# profitsbot — Trading Bot Profits (Phintraco Sekuritas)

Bot trading saham IDX otomatis via API **Profits** (Phintraco Sekuritas, profits.co.id).
Strategi: sinyal **ADX** (+DI/-DI cross & trend) + filter RSI/SMA20 + SL **Donchian**
(di-porting dari strategi protraderbot yang sudah cuan).

```
Harga OHLC (Yahoo .JK) ──> Indikator (ADX/RSI/Donchian) ──> Sinyal BUY/SELL
       │                                                         │
       └─ real-time (Protrader API lokal / Profits REST) ──> Order (Profits)
```

## 📌 Prasyarat

- Python 3.10+ (Windows)
- Akun Profits (Phintraco) — username, password, PIN trading
- (Opsional) Bot protrader jalan + `api_server` port 8777 untuk harga real-time PMP

## 🚀 Setup

```bash
cd profitsbot

# 1. Buat virtual env & install dependencies
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2. Siapkan kredensial & config
cp .env.example .env          # lalu isi PROFITS_USERNAME / PROFITS_PASSWORD / PROFITS_PIN
```

⚠️ **`.env` berisi kredensial — JANGAN commit/push!** (sudah di-gitignore)

## ▶️ Cara Run

### 1. Scan sekali (nontrade — aman, tidak ada order dikirim)

```bash
./.venv/Scripts/python.exe profits_bot.py
```

### 2. Scan saham tertentu

```bash
./.venv/Scripts/python.exe profits_bot.py --symbols BBCA,ANTM
```

### 3. Loop otomatis (scan top values tiap 3 menit saat market buka)

```bash
./.venv/Scripts/python.exe profits_bot.py --loop
# config: PROFITS_CYCLE_MINUTES=3, PROFITS_SCAN_INTERVAL=15m,
#         PROFITS_MARKET_OPEN=09:00, PROFITS_MARKET_CLOSE=15:30 (WIB, weekday)
```

### 4. Mode TRADE (eksekusi order beneran — ⚠️ HATI-HATI!)

```bash
./.venv/Scripts/python.exe profits_bot.py --loop --trade
# atau: --live (alias), PROFITS_BOT_MODE=trade di .env
```

### 5. Loop + eksekusi sinyal otomatis (tetap DRY-RUN kecuali --trade)

```bash
./.venv/Scripts/python.exe profits_bot.py --loop --execute
```

### 6. Test cycle langsung di saham tertentu

```bash
PROFITS_TEST_SYMBOL=BBCA ./.venv/Scripts/python.exe profits_bot.py
```

### Argumen CLI

| Flag | Fungsi |
|---|---|
| `--loop` | loop scan tiap cycle (default 3 menit) saat market buka |
| `--cycle N` | override cycle (menit) |
| `--interval TF` | override timeframe sinyal (15m, 5m, 1d, dst) |
| `--symbols A,B` | scan saham tertentu |
| `--execute` | auto-eksekusi sinyal (DRY-RUN) |
| `--trade` / `--live` | mode TRADE — order dikirim beneran |
| `--nontrade` / `--dry-run` | mode nontrade (default) |

## ⚙️ Config (`.env`) — analog protraderbot

```ini
# Chart
PROFITS_CHART_RESOLUTION=15            # timeframe: 1,3,5,15,30,45,60,120,240,D
PROFITS_CHART_COUNTBACK=2000           # max bar (best effort — Yahoo)

# Indikator (Basis ADX)
PROFITS_ADX_PERIOD=14                  # period ADX (Wilder)
PROFITS_ADX_THRESHOLD=20               # minimal ADX utk sinyal tren
PROFITS_DONCHIAN_PERIOD=10             # SL Donchian (lookback = 2.8 x 10 = 28 bar)
PROFITS_BOLLINGER_PERIOD=20
PROFITS_BOLLINGER_STD=2

# Watchlist & Filter
PROFITS_TOP_VALUES=15                  # top N by value (top-stocks)
PROFITS_FILTER_DISCRETE=1              # skip saham "discrete" (banyak bar flat)
PROFITS_MAX_FLAT_PCT=50                # threshold flat %

# Mode & Eksekusi
PROFITS_BOT_MODE=nontrade              # nontrade = scan/log; trade = order REAL
PROFITS_TRADE_LOT=0                    # lot per order (1 = uji coba; 0 = sizing)
PROFITS_TEST_SYMBOL=                   # test cycle langsung di saham itu
PROFITS_USE_FLIP=1                     # SELL sinyal saat LONG = tutup posisi penuh
PROFITS_CYCLE_MINUTES=3                # interval scan (menit)
PROFITS_SCAN_INTERVAL=15m              # timeframe sinyal (Yahoo)

# Sizing / Risk
PROFITS_CAPITAL=100000000              # modal default 100 juta
PROFITS_RISK_PCT=1.0                   # risk exposure per posisi (%)
PROFITS_ORDER_VALUE=20000000           # CAP nilai per order (lot size > cap -> dipangkas)
```

**Sizing (TRADE_LOT=0, persis protraderbot):**
```
risk_amount = CAPITAL x RISK_PCT/100
lot = floor(risk_amount / (|harga - SL| x 100))
lot_final = min(lot, cap 20jt / harga/100, sisa cash)   # 3 lapis guard
```

## 🛡️ Safety (built-in)

- **CASH ONLY** — order ditolak kalau nilai > cash real (bukan maxLimit/leverage!)
- **Guard akumulasi** — total semua order plan ≤ cash
- **Anti-numpuk** — skip BUY kalau sudah punya posisi saham itu
- **DRY-RUN default** — order hanya log, tidak dikirim (kecuali `--trade`)
- **qty = LOT** (1 lot = 100 lembar) — terverifikasi live

## 🧩 Struktur

```
profits_bot.py      # bot utama: loop, sinyal, eksekusi, guard
profits_client.py   # API client Profits (login, order, SL, balance)
indicators.py       # ADX/RSI/MACD/Bollinger/Donchian/SMA
profits_ws.py       # WebSocket streaming (harga live)
cdp_*.py            # tooling reverse-engineering (dokumentasi API)
dump/               # hasil dump frontend (bundle JS)
AGENTS.md           # dokumentasi teknis lengkap (endpoint, auth, order)
```

## 🔍 Referensi teknis (ringkas)

- API: `https://next-dev.profits.co.id/api` — `Authorization: Bearer <token>`
- Login: password dienkripsi AES (passphrase publik bundle); `X-APP-PLATFORM: windows`
- Order: `POST /portfolio/order` `{qty (LOT), isBuy, price, code, orderType, expire:"day"}`
- SL: `POST /automation/stoploss` (butuh posisi) — cancel: `/automation/stoploss/<id>/cancel`
- WS: `wss://stream.profits.co.id/market?key=<token>` — subscribe `sub|market|price|BBCA`
- Data OHLC: Yahoo Finance (`ANTM.JK`) — 1m/5m/15m/30m/60m/1d (delay ±10 menit)
- Harga real-time: Profits REST `/catalog/company/<CODE>/price` (24/7) + fallback chain
  `Protrader API (localhost:8777) -> Yahoo`
- Maintenance server: 22:00-00:05 WIB (feed kosong)

Detail lengkap di [AGENTS.md](AGENTS.md).
