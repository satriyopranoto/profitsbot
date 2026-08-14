"""READ-ONLY: login + daftar posisi (portfolio/stock) + stoploss terpasang (automation/stoploss)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profits_client as pc
import profits_bot as pb

bot = pb.ProfitsBot()
try:
    bot.login()
except Exception as e:
    print("login error:", e); sys.exit(1)
bot.trade_login()

print("\n=== POSISI (portfolio/stock) ===")
st = bot.get_stocks()
rows = st.get("data") or []
if not rows:
    print("(kosong / gagal:", json.dumps(st)[:200], ")")
for x in rows:
    print(f"  {x.get('code'):6s} qty={x.get('total'):>8} avg={x.get('avgPrice') or 0:>10} last={x.get('price') or 0:>10}")

print("\n=== STOP LOSS TERPASANG (automation/stoploss) ===")
sls = bot.get_stop_losses()
sldata = sls.get("data") or []
if isinstance(sldata, dict):
    sldata = sldata.get("list") or sldata.get("items") or []
if not sldata:
    print("(kosong / raw:", json.dumps(sls)[:300], ")")
for s in sldata:
    print(" ", json.dumps(s, ensure_ascii=False)[:220])

print("\n=== ORDER AKTIF (portfolio/order) ===")
od = bot.get_orders()
oddata = od.get("data") or []
if not oddata:
    print("(kosong / raw:", json.dumps(od)[:200], ")")
for o in oddata:
    print(" ", json.dumps(o, ensure_ascii=False)[:200])
