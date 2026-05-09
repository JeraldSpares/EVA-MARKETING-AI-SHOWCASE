@echo off
setlocal EnableDelayedExpansion
call "%~dp0load_env.bat"
cd /d "%~dp0"
python social_listening.py
endlocal
