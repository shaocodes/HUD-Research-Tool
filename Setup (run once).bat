@echo off
cd /d "%~dp0"
echo Installing what the Studio needs. This can take a few minutes the first time.
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Something went wrong. Is Python installed? Get it from python.org and tick "Add python.exe to PATH".
) else (
  echo.
  echo Done. From now on just double-click Start.bat
)
pause
