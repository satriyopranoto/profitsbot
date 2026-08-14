"""PASANG 11 SL Donchian (harga valid tick) — LIVE order di akun Profits."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profits_bot as pb

SLS = {
    "AADI": 9000, "BIPI": 146, "DSSA": 955, "ENRG": 1255, "IATA": 119,
    "MDIA": 240, "PPRE": 99, "PTBA": 2320, "PTRO": 5150, "SMGR": 1485,
    "UNTR": 23050,
}

bot = pb.ProfitsBot()
bot.live = True  # kirim beneran (bukan dry-run)
try:
    bot.login()
except Exception as e:
    print("login error:", e); sys.exit(1)
bot.trade_login()

# qty per saham dari posisi aktual (lembar -> lot)
qtys = {}
try:
    st = bot.get_stocks()
    for x in (st.get("data") or []):
        q = x.get("total") or 0
        if q > 0:
            qtys[x.get("code")] = max(int(q // 100), 1)
except Exception as e:
    print("baca posisi gagal:", e)

ok, fail = [], []
for code, trig in SLS.items():
    qty = qtys.get(code, 1)
    try:
        r = bot.set_stop_loss(code, trig, qty)
        d = r.get("data") if isinstance(r, dict) else None
        if d and str(d) not in ("", "None"):
            ok.append((code, trig, qty, d))
            print(f"  [OK] {code} SL {trig} qty {qty}lot -> {d}")
        else:
            fail.append((code, trig, r))
            print(f"  [GAGAL] {code} SL {trig} qty {qty}lot -> {json.dumps(r, ensure_ascii=False)[:200]}")
    except Exception as e:
        fail.append((code, trig, str(e)))
        print(f"  [ERROR] {code}: {e}")

print(f"\n=== HASIL: {len(ok)} OK, {len(fail)} GAGAL ===")
if fail:
    print("GAGAL:", [f[0] for f in fail])
