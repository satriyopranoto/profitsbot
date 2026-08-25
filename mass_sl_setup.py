#!/usr/bin/env python3
"""UTILITY (LIVE): pasang Stop Loss utk SEMUA holding profitsbot yang belum ber-SL.

Kenapa: profitsbot TIDAK punya reconciliation SL otomatis => ada holding "yatim"
tanpa SL (insiden 2026-08-25: cuma 4/10 holding ber-SL). Utility ini menambal:

  * Ambil posisi (portfolio/stock) + daftar SL aktif (automation/stoploss).
  * Posisi yang SUDAH ber-SL -> SKIP (tidak ditimpa).
  * Posisi tanpa SL -> hitung SL Donchian 2.8x10 (min low M15 28 bar, paritas
    EA Strong / protraderbot). Kalau OHLC n/a -> pakai level MANUAL (bila ada).
  * SKIP kalau SL >= harga current (tembus -> langsung ke-trigger, sia-sia).
  * qty = lot (portfolio total // 100). kirim set_stop_loss(). Verifikasi ulang.

PENTING qty = LOT (100 lembar) — VERIFIKASI LIVE (profits API).

Usage:
  python mass_sl_setup.py --dry-run  # tampilkan RENCANA saja (AMAN, tidak kirim)
  python mass_sl_setup.py            # eksekusi LIVE utk posisi tanpa SL

Manual override: ubah MANUAL di bawah (mis. {"DOOH": 288}) utk level tertentu
yg OHLC-nya tak terbaca. [] = tidak ada override.
"""
import os, sys, json  # noqa: F401
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profits_bot as pb  # noqa: E402

# ===== konfigurasi =====
DC_MULT, DC_PER = 2.8, 10          # Donchian lookback = DC_MULT x DC_PER bar (M15)
# level manual utk saham yg OHLC otomatis tak terbaca (ganti sesuai kebutuhan)
MANUAL = {"DOOH": 288}             # contoh: DOOH 288 (approved user)
# ========================


def _norm(data):
    """Normalisasi respons automation (data bisa list langsung atau {list/items})."""
    if isinstance(data, dict):
        data = data.get("list") or data.get("items") or []
    return data or []


def run(dry_run):
    bot = pb.ProfitsBot()
    bot.live = not dry_run
    try:
        bot.login()
    except Exception as e:
        print("login error:", e); sys.exit(1)
    bot.trade_login()

    # posisi + qty lot
    st = bot.get_stocks()
    rows = st.get("data") or []
    qtys = {x.get("code"): max(int((x.get("total") or 0) // 100), 1)
            for x in rows if (x.get("total") or 0) > 0}

    # SL yg sudah ada (jangan ditimpa)
    sls = bot.get_stop_losses()
    have_sl = {s.get("code") for s in _norm(sls.get("data") or [])}

    mode = "DRY-RUN — tidak kirim order" if dry_run else "LIVE — order terkirim"
    print(f"=== MASS SL SETUP ({mode}) ===")
    print(f"  posisi: {len(qtys)} | sudah ber-SL (skip): {len(have_sl)}")

    # bangun rencana utk yg tanpa SL
    plan = {}
    for code in qtys:
        if code in have_sl:
            continue
        sl = bot.sl_donchian_price(code, "15m", DC_MULT, DC_PER)
        src = "Donchian"
        if sl is None:
            if code in MANUAL:
                sl, src = MANUAL[code], "MANUAL"
            else:
                print(f"  {code:<6} OHLC n/a & tanpa override -> SKIP (butuh level manual)")
                continue
        # skip kalau tembus (SL >= current)
        try:
            px = bot.price(code)
        except Exception:
            px = None
        cur = (px or {}).get("last") or (px or {}).get("sellPrice") or (px or {}).get("price") or 0
        if cur and sl >= cur:
            print(f"  {code:<6} SL {sl} >= current {cur} (tembus) -> SKIP, butuh level manual")
            continue
        plan[code] = (sl, src)
        print(f"  {code:<6} lot={qtys[code]:>5}  SL={sl}  ({src})")

    if dry_run or not plan:
        print(f"\n  RENCANA: {len(plan)} posisi utk dipasang. (dry-run selesai, tidak kirim)")
        return

    print(f"\n  Eksekusi {len(plan)} posisi...")
    ok, fail = [], []
    for code, (trig, _src) in plan.items():
        qty = qtys.get(code, 1)
        r = bot.set_stop_loss(code, trig, qty)
        rs = json.dumps(r, ensure_ascii=False)
        if r.get("errors") or r.get("error"):
            fail.append(code)
            print(f"  {code:<6} GAGAL trig={trig} qty={qty}: {rs[:160]}")
        else:
            ok.append(code)
            print(f"  {code:<6} pasang trig={trig} qty={qty}: {rs[:100]}")

    print(f"\n=== RINGKASAN OK: {len(ok)} / FAIL: {len(fail)} ===")

    # verifikasi ulang
    sls2 = bot.get_stop_losses()
    have2 = {s.get("code") for s in _norm(sls2.get("data") or [])}
    missing = [c for c in qtys if c not in have2]
    print(f"  Posisi tanpa SL tersisa: {missing if missing else 'TIDAK ADA — semua ber-SL'}")


if __name__ == "__main__":
    run("--dry-run" in sys.argv)