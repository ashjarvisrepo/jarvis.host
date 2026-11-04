@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: restore.bat jarvis_shop_YYYYMMDDTHHMMSSZ.sqlite3
  echo Verify the backup with /backup_verify before restoring it.
  exit /b 2
)
if not "%~nx1"=="%~1" (
  echo Pass only a filename from the backups folder; paths are not accepted.
  exit /b 2
)
if /I not "%~x1"==".sqlite3" (
  echo Backup must be a .sqlite3 file.
  exit /b 2
)
set "SOURCE=%CD%\backups\%~1"
set "TARGET=%CD%\data\jarvis_shop.sqlite3"
if not exist "%SOURCE%" (
  echo Backup not found: %SOURCE%
  exit /b 2
)
echo Stop JARVIS SHOP before restoring. This operation replaces the active database.
choice /C YN /M "Restore %~1 now"
if errorlevel 2 exit /b 1
if not exist "%CD%\data" mkdir "%CD%\data"
if exist "%TARGET%" (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "STAMP=%%i"
  copy /y "%TARGET%" "%CD%\backups\pre_restore_%STAMP%.sqlite3" >nul
  if errorlevel 1 (
    echo Could not preserve the current database; restore cancelled.
    exit /b 1
  )
)
copy /y "%SOURCE%" "%TARGET%" >nul
if errorlevel 1 (
  echo Restore copy failed. Preserve the backup and inspect the data folder.
  exit /b 1
)
echo Restore completed. Start the bot and inspect logs before accepting new orders.
endlocal
