#!/bin/bash
# Housekeeping SL orphaned profitsbot — scan + cancel orphaned (LIVE).
# Dijadwalkan tiap hari kerja (Mon-Fri) 16:15 WIB, setelah market tutup.
# Stdout diteruskan verbatim ke user; exit non-zero => alert (ada yang gagal cancel).
cd /c/Users/satri/code/profitsbot || exit 9
/c/Users/satri/code/profitsbot/.venv/Scripts/python.exe housekeep_sl.py