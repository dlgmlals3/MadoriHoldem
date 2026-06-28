@echo off
echo [마도리 홀덤] 서버 시작 중...
cd /d "%~dp0server"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
