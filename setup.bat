@echo off
REM ติดตั้ง Thai API Hub ครั้งแรก
cd /d %~dp0
if not exist .env copy .env.example .env
if not exist .venv (
  echo [1/2] สร้าง virtual environment...
  python -m venv .venv
)
echo [2/2] ติดตั้ง dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q
echo.
echo เสร็จ! รันเซิร์ฟเวอร์ด้วย start.bat
pause
