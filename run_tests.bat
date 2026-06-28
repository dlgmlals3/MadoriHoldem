@echo off
echo [마도리 홀덤] 단위 테스트 실행 중...
cd /d "%~dp0server"
python -m pytest tests/ -v
pause
