@echo off
setlocal EnableDelayedExpansion
call "%~dp0load_env.bat"
cd /d "%~dp0"
python weekly_analytics_report.py
endlocal
