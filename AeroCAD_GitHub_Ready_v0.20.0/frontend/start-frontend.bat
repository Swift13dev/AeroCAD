@echo off
setlocal
cd /d "%~dp0"
call npm install
call npm run dev
endlocal
