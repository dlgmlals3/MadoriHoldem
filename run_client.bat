@echo off
echo [마도리 홀덤] 클라이언트 서버 시작 중 (http://localhost:8080)...
echo 브라우저에서 http://localhost:8080 을 열어주세요.
python -m http.server 8080 --directory "%~dp0client"
pause
