@echo off
title ProfitsBot - LIVE
cd /d C:\Users\satri\code\profitsbot
echo ============================================
echo  ProfitsBot - foreground (tutup window = stop)
echo ============================================
.venv\Scripts\python.exe profits_bot.py --loop
echo.
echo Bot berhenti. Tekan tombol apa saja...
pause >nul
