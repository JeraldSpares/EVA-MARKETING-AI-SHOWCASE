@echo off
setlocal EnableDelayedExpansion
echo Stopping any old dashboard servers...
taskkill /F /IM python.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo Starting Enderun Marketing Hub...
call "%~dp0load_env.bat"
cd /d "%~dp0"
python dashboard.py
pause
endlocal
