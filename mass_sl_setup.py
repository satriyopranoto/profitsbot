#!/usr/bin/env python3
"""UTILITY (LIVE): pasang Stop Loss utk SEMUA holding profitsbot yang belum ber-SL.

Kenapa: posisi bisa "yatim" tanpa SL (mis. PTBA 05-Okt-2026). Utility ini menambal:

  * Ambil posisi (portfolio/stock) + daftar SL aktif (automation/stoploss).
  * Posisi yang SUDAH ber-SL -> SKIP (tidak ditimpa).
  * Posisi tanpa SL -> hitung SL Donchian 2.8x10 = min(low, 28 bar) pada TF BOT
    (`pb.SCAN_INTERVAL`, mis. 30m — BUKAN M15 hardcode) lalu trigger = 1 tick IDX
    di bawahnya via `bot.sl_trigger()` (tick-aligned; paritas protraderbot next_tick_down).
  * SKIP kalau trigger >= harga current (tembus -> langsung ke-trigger, sia-sia).
  * qty = lot (portfolio total // 100). kirim set_stop_loss(). Verifikasi ulang.

PENTING qty = LOT (100 lembar) — VERIFIKASI LIVE (profits API).

Usage:
  python mass_sl_setup.py --dry-run  # tampilkan RENCANA saja (AMAN, tidak kirim)
  python mass_sl_setup.py            # eksekusi LIVE utk posisi tanpa SL

Manual override: ubah MANUAL di bawah (mis. {"DOOH": 288}) utk level tertentu
yg OHLC-nya tak terbaca. {} = tidak ada override.

RIWAYAT FIX (05-Okt-2026):
  - TF: dulu hardcode "15m" -> level dari TF SALAH saat TF bot 30m (insiden SL PTBA:
    M15 3120 vs M30 yang benar 3020). Kini `pb.SCAN_INTERVAL` (TF bot).
  - Guard tembus: dulu `bot.price()` — METHOD ITU TIDAK ADA -> AttributeError ditelan
    try/except -> `cur=0` -> guard `sl>=cur` SELALU LOLOS (SL tembus ikut terpasang).
    Kini `bot.get_price()` (REST 24/7) → guard benar-benar bekerja.
  - Trigger: dulu level LLV mentah (bisa bukan kelipatan tick, mis. 3130) -> kini
    `bot.sl_trigger()` (round-down ke tick lalu -1 tick).
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profits_bot as pb        # noqa: E402
import indicators as ind        # noqa: E402

# ===== konfigurasi =====
DC_MULT, DC_PER = 2.8, 10          # Donchian lookback = DC_MULT x DC_PER bar (TF = pb.SCAN_INTERVAL)
TF = pb.SCAN_INTERVAL              # ⚠️ TF BOT (jangan hardcode "15m")
# level manual utk saham yg OHLC otomatis tak terbaca (ganti sesuai kebutuhan)
MANUAL = {}                        # contoh: {"DOOH": 288} (approved user)
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
        print("login error:", e)
        sys.exit(1)
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
    print(f"=== MASS SL SETUP ({mode}) | TF={TF} (Donchian {DC_MULT}x{DC_PER} = {DC_MULT*DC_PER:g} bar) ===")
    print(f"  posisi: {len(qtys)} | sudah ber-SL (skip): {len(have_sl)}")

    # bangun rencana utk yg tanpa SL
    plan = {}
    for code in qtys:
        if code in have_sl:
            continue
        level = bot.sl_donchian_price(code, TF, DC_MULT, DC_PER)
        src = "Donchian"
        if level is None:
            if code in MANUAL:
                level, src = MANUAL[code], "MANUAL"
            else:
                print(f"  {code:<6} OHLC n/a & tanpa override -> SKIP (butuh level manual)")
                continue
        # trigger tick-aligned (1 tick di bawah level) — bukan level mentah
        trig = bot.sl_trigger(level)
        # skip kalau tembus (trigger >= current) — pakai get_price() (REST 24/7);
        # ⚠️ JANGAN `bot.price()` (method tidak ada -> guard mati).
        try:
            px = bot.get_price(code) or {}
        except Exception as e:
            px = {}
            print(f"  {code:<6} get_price error: {e}")
        cur = px.get("current") or px.get("last") or 0
        if cur and trig >= cur:
            print(f"  {code:<6} trigger {trig} >= current {cur} (TEMBUS) -> SKIP, butuh level manual")
            continue
        plan[code] = (trig, src, level)
        print(f"  {code:<6} lot={qtys[code]:>5}  level={level} (tick {ind.tick_size(int(level))}) "
              f"-> trigger={trig}  current={cur}  [{src}]")

    if dry_run or not plan:
        print(f"\n  RENCANA: {len(plan)} posisi utk dipasang. (dry-run selesai, tidak kirim)")
        return

    print(f"\n  Eksekusi {len(plan)} posisi...")
    ok, fail = [], []
    for code, (trig, _src, _lvl) in plan.items():
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
