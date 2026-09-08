@echo off
REM รัน Thai API Hub
cd /d %~dp0
if not exist .venv (
  echo ยังไม่ได้ติดตั้ง — รัน setup.bat ก่อน
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python run.py
