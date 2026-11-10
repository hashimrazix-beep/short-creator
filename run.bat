@echo off
title Short Creator
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up, this takes a few minutes...
  python -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :fail
)
".venv\Scripts\python.exe" server.py
goto :eof
:fail
echo Setup failed. Make sure Python 3.10+ and FFmpeg are installed.
pause
