@echo off
title Update Penghibur Malam
color 0a
cd /d "%~dp0"

echo ------------------------------------------
echo     UPDATE: PENGHIBUR MALAM
echo ------------------------------------------
echo.
echo [INFO] Menarik update dari GitHub...
git pull

echo.
echo [INFO] Menginstall dependencies baru (jika ada)...
pip install -r requirements.txt --upgrade

echo.
echo [SUCCESS] Update selesai!
echo.
pause
