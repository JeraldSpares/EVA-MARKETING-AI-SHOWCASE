@echo off
setlocal EnableDelayedExpansion
call "%~dp0load_env.bat"
cd /d "%~dp0"
pip install flask requests -q
python webhook_server.py
endlocal
