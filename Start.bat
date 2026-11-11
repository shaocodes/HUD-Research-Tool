@echo off
cd /d "%~dp0"
title HUD Study Studio
echo Starting HUD Study Studio... your browser will open. Keep this window open while you work.
python studio\server.py
if errorlevel 1 (
  echo.
  echo Could not start. Run "Setup (run once).bat" first, or check that Python is installed.
  pause
)
