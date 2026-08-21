#!/usr/bin/env python3
"""housekeep_sl — bersihkan Stop Loss (automation/stoploss) ORPHANED di Profits.

Kontek: selama trading, posisi bisa keluar via TP/FLIP tanpa menyentuh SL ->
automation SL tetap ACTIVE padahal sahamnya sudah TIDAK ada di posisi
(portfolio/stock qty=0). SL orphaned ini membingungkan & berisiko (bisa jual
kosong / nge-blok). Program ini:

  1. get_stop_losses    -> daftar automation stoploss
  2. get_stocks         -> posisi yang MASIH dipunyai (total qty > 0)
  3. SL yang code-nya TIDAK ada di posisi = ORPHANED -> cancel_automation(id, "stoploss")
  4. Lapor ringkasan; dukung --dry-run (cek saja, tanpa cancel).

Type "stoploss" WAJIB di URL cancel (bukan /automation/<id>/cancel -> 404!)
-- TERVERTIFIKASI live.

Usage:
  .venv/Scripts/python.exe housekeep_sl.py --dry-run   # cek saja (AMAN)
  .venv/Scripts/python.exe housekeep_sl.py             # scan + CANCEL orphaned (LIVE)
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profits_bot as pb

# Status SL yang dianggap BUKAN aktif -> jangan dicancel / jangan dianggap orphan.
TERMINAL_STATUS = ("CANCEL", "WITHDRAWN", "EXPIRED", "REJECTED", "EXECUTED", "DONE")


def norm_data(resp):
    """Normalisasi respon -> list SL; data bisa list atau dict {list/items}."""
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict):
        data = data.get("list") or data.get("items") or []
    return data or []


def main():
    ap = argparse.ArgumentParser(description="Housekeeping SL orphaned Profits")
    ap.add_argument("--dry-run", action="store_true",
                    help="scan saja, tanpa cancel (rekomendasi cek dulu)")
    args = ap.parse_args()

    bot = pb.ProfitsBot()
    try:
        bot.login()
        bot.trade_login()
    except Exception as e:
        print(f"[FAIL] login/trade_login gagal: {e}")
        return 1

    # 1. SL aktif (skip status terminal)
    try:
        sl_all = norm_data(bot.get_stop_losses())
    except Exception as e:
        print(f"[FAIL] get_stop_losses gagal: {e} — batal (jangan cancel buta)")
        return 1
    active = [s for s in sl_all
              if not any(k in (s.get("status") or "").upper() for k in TERMINAL_STATUS)]
    print(f"SL (total {len(sl_all)}, aktif {len(active)}):", end=" ")
    if active:
        print(", ".join(sorted(f"{s.get('code')}@{s.get('triggerPrice')}"
                               for s in active)))
    else:
        print("(tidak ada)")

    # 2. Posisi (saham yang masih dipunyai)
    try:
        pos = bot.get_stocks()
    except Exception as e:
        print(f"[FAIL] get_stocks gagal: {e} — batal (fail-closed)")
        return 1
    held = {x.get("code") for x in (pos.get("data") or [])
            if (x.get("total") or 0) > 0}
    print(f"Posisi: {len(held)} saham ->",
          ", ".join(sorted(held)) if held else "(kosong)")

    if not active:
        print("Tidak ada SL aktif — tidak ada yang perlu di-housekeep.")
        return 0

    # 3. Deteksi orphan
    keep = [s for s in active if s.get("code") in held]
    orphaned = [s for s in active if s.get("code") not in held]

    print("=== RINGKASAN ===")
    print(f"SL tetap valid (saham masih di posisi): {len(keep)}")
    for s in sorted(keep, key=lambda x: x.get("code", "")):
        print(f"  KEEP  {s.get('code',''):6s} trig={s.get('triggerPrice')} "
              f"status={s.get('status')} id={s.get('id')}")

    if not orphaned:
        print("TIDAK ada SL orphaned — semuanya berpasangan dgn posisi. Bersih.")
        return 0

    print(f"SL ORPHANED (saham sudah TIDAK di posisi): {len(orphaned)}")
    for s in sorted(orphaned, key=lambda x: x.get("code", "")):
        print(f"  ORPH {s.get('code',''):6s} trig={s.get('triggerPrice')} "
              f"status={s.get('status')} id={s.get('id')}")

    if args.dry_run:
        print(f"--dry-run: {len(orphaned)} SL orphaned TIDAK dicancel. Jalankan "
              f"lagi tanpa --dry-run utk cancel.")
        return 0

    # 4. Cancel (LIVE)
    cancelled, failed = [], []
    for s in sorted(orphaned, key=lambda x: x.get("code", "")):
        oid = s.get("id")
        try:
            r = bot.cancel_automation(oid, "stoploss")
            # sukses = errors null/tidak ada + data UUID hadir. "errors": null
            # BUKAN gagal (cek kehadiran key "errors" salah tanda -> salah report
            # [FAIL] pdhl sukses, insiden CUAN 2026-08-21).
            is_ok = not (isinstance(r, dict) and r.get("errors"))
            if is_ok:
                cancelled.append(s)
                print(f"  [OK] CANCEL {s.get('code',''):6s} trig={s.get('triggerPrice')} "
                      f"id={oid} -> {json.dumps(r, ensure_ascii=False)[:80]}")
            else:
                failed.append(s)
                print(f"  [FAIL] CANCEL {s.get('code',''):6s} id={oid} -> "
                      f"{json.dumps(r, ensure_ascii=False)[:140]} (SL masih terpasang — cek manual)")
        except Exception as e:
            failed.append(s)
            print(f"  [FAIL] CANCEL {s.get('code',''):6s} id={oid} -> {e} (cek manual)")
        time.sleep(0.3)

    print(f"=== SELESAI: {len(cancelled)} di-cancel, {len(failed)} gagal (perlu "
          f"manual), {len(keep)} tetap valid ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
