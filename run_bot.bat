@echo off
title Omnia Music Bot - Discord
color 0f
cd /d "%~dp0"

echo ------------------------------------------
echo         DISCORD BOT: OMNIA MUSIC
echo ------------------------------------------
echo.
echo [INFO] Menjalankan bot...
python main.py

echo.
echo [ERROR] Bot berhenti atau ada masalah!
echo [INFO] Tekan tombol apa saja untuk keluar...
pause >nul
