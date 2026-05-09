@echo off
setlocal EnableDelayedExpansion
call "%~dp0load_env.bat"
set AUTO_SEND=true
cd /d "%~dp0"
python send_drip_email.py
endlocal
