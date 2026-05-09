@echo off
setlocal EnableDelayedExpansion
call "%~dp0load_env.bat"
set AUTO_POST=true
cd /d "%~dp0"
python post_to_facebook.py
endlocal
