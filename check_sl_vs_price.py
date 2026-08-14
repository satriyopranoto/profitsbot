"""READ-ONLY: cek SL profitsbot vs current price — SL harus di bawah current (long)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profits_bot as pb

bot = pb.ProfitsBot()
try:
    bot.login()
except Exception as e:
    print("login error:", e); sys.exit(1)
bot.trade_login()

sls = bot.get_stop_losses()
data = sls.get("data") or []
if isinstance(data, dict):
    data = data.get("list") or data.get("items") or []
print(f"TOTAL SL terpasang: {len(data)}")

codes = [s.get("code") for s in data]
prices = bot._live_prices(codes, {})
if not prices:
    # fallback: cek satu-satu
    for c in codes:
        try:
            p = bot._live_prices([c], {})
            if p: prices.update(p)
        except Exception:
            pass

print(f"\n{'Code':6s} {'SL trigger':>10} {'Current':>10} {'Status':>14}")
for s in data:
    code = s.get("code")
    trig = s.get("triggerPrice")
    cur = prices.get(code, 0)
    if cur and trig:
        st = "OK (di bawah)" if trig < cur else "!! DI ATAS CURRENT !!"
        mark = "⚠️" if trig >= cur else ""
    elif not cur:
        st = "?? harga tak kebaca"; mark = "?"
    else:
        st = "??"; mark = "?"
    print(f"{code:6s} {trig:>10} {cur:>10} {st:>14} {mark}")
