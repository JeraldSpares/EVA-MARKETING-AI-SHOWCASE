@echo off
REM Loads variables from .env into the current cmd session.
REM Lines starting with # are skipped. Format: KEY=VALUE
if not exist "%~dp0.env" (
    echo [load_env] WARNING: .env not found at %~dp0.env
    exit /b 0
)
for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
    set "_k=%%A"
    if not "!_k:~0,1!"=="#" if not "%%A"=="" set "%%A=%%B"
)
exit /b 0
