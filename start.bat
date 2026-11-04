@echo off
title JARVIS SHOP EXTREME
cd /d "%~dp0"
echo ==========================================
echo       JARVIS SHOP EXTREME - START
echo ==========================================
if not exist .venv\Scripts\activate.bat (
  echo ERROR: Python environment not found.
  echo Double-click setup.bat first and wait for it to finish.
  pause
  exit /b 1
)
if not exist .env (
  echo ERROR: .env not found. Copy .env.example to .env and add your Discord bot token.
  pause
  exit /b 1
)
echo Activating Python environment...
call .venv\Scripts\activate
if errorlevel 1 (
  echo ERROR: Could not activate .venv. Run setup.bat again.
  pause
  exit /b 1
)
echo Launching bot. Keep this window open while the bot is online.
echo A successful connection prints the bot account name below.
echo.
python main.py
if errorlevel 1 (
  echo.
  echo The bot stopped with an error. Read the message above, fix the cause, then run start.bat again.
)
echo.
echo JARVIS SHOP has stopped.
pause
