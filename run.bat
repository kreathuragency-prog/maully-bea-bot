@echo off
echo ══════════════════════════════════════
echo   Bea Bot - Importadora Maully
echo ══════════════════════════════════════
echo.

pip install -r requirements.txt --quiet 2>nul
python main.py
pause
