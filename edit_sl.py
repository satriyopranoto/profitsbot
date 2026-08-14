"""EDIT SL profitsbot: BIPI 146->145, IATA 119->118 (cancel lama + pasang baru)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profits_bot as pb

NEW = {"BIPI": 145, "IATA": 118}

bot = pb.ProfitsBot()
bot.live = True
try:
    bot.login()
except Exception as e:
    print("login error:", e); sys.exit(1)
bot.trade_login()

sls = bot.get_stop_losses()
data = sls.get("data") or []
if isinstance(data, dict):
    data = data.get("list") or data.get("items") or []

qtys = {}
try:
    st = bot.get_stocks()
    for x in (st.get("data") or []):
        q = x.get("total") or 0
        if q > 0:
            qtys[x.get("code")] = max(int(q // 100), 1)
except Exception as e:
    print("baca posisi gagal:", e)

for code, trig in NEW.items():
    # cari SL lama
    olds = [s for s in data if s.get("code") == code]
    print(f"=== {code} -> {trig} ===")
    for o in olds:
        oid = o.get("id")
        r = bot.cancel_automation(oid, "stoploss")
        print(f"  cancel {o.get('code')} trig {o.get('triggerPrice')} id {oid}: {json.dumps(r, ensure_ascii=False)[:120]}")
    qty = qtys.get(code, 1)
    r = bot.set_stop_loss(code, trig, qty)
    print(f"  pasang baru {code} {trig} qty {qty}lot: {json.dumps(r, ensure_ascii=False)[:120]}")

# verifikasi
print("\n=== VERIFIKASI ===")
sls2 = bot.get_stop_losses()
d2 = sls2.get("data") or []
if isinstance(d2, dict):
    d2 = d2.get("list") or d2.get("items") or []
for s in d2:
    if s.get("code") in NEW or s.get("code") in ("BIPI", "IATA"):
        print(f"  {s.get('code')}: trigger={s.get('triggerPrice')} status={s.get('status')} id={s.get('id')}")
