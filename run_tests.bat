@echo off
title JARVIS SHOP EXTREME - TESTS
cd /d "%~dp0"
echo Installing test tools and running the test suite...
if not exist .venv\Scripts\activate.bat (
  echo ERROR: Python environment not found. Run setup.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate
pip install pytest pytest-asyncio
if errorlevel 1 (
  echo ERROR: Could not install test tools. Check your internet connection.
  pause
  exit /b 1
)
python -m pytest -q
if errorlevel 1 echo Some tests failed or could not run. Read the report above.
pause
