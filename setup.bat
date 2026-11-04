@echo off
title JARVIS SHOP EXTREME - SETUP
cd /d "%~dp0"
echo ==========================================
echo       JARVIS SHOP EXTREME - SETUP
echo ==========================================
echo Checking for Python 3.11 or newer...
py -3 --version
if errorlevel 1 (
  echo ERROR: Python launcher not found. Install Python 3.11 or newer and select "Add Python to PATH".
  pause
  exit /b 1
)
echo Creating the local Python environment...
py -3 -m venv .venv
if errorlevel 1 (
  echo ERROR: Could not create .venv.
  pause
  exit /b 1
)
call .venv\Scripts\activate
echo Installing required packages. This may take a few minutes...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo ERROR: Could not upgrade pip. Check your internet connection and try again.
  pause
  exit /b 1
)
pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Package installation failed. Check your internet connection and Python version.
  pause
  exit /b 1
)
if not exist .env copy .env.example .env
echo.
echo Setup complete. Add your Discord token to .env, configure config\settings.yaml, then run start.bat.
pause
