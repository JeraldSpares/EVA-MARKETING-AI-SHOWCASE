@echo off
:: ============================================================
::  Enderun Extension - Task Scheduler Setup
::  RIGHT-CLICK this file and choose "Run as administrator"
:: ============================================================

echo.
echo  Enderun Extension - Scheduling Automation Tasks
echo  ================================================
echo.

SET FOLDER=C:\Users\Admin\OneDrive\Desktop\MARKETING DEPARTMENT

:: --- Daily Drip Email (8:00 AM every day) ---
SCHTASKS /CREATE /TN "Enderun - Daily Drip Email" ^
  /TR "\"%FOLDER%\run_daily_email.bat\"" ^
  /SC DAILY /ST 08:00 /F /RL HIGHEST
IF %ERRORLEVEL%==0 (
    echo  [OK] Daily Drip Email scheduled at 8:00 AM
) ELSE (
    echo  [FAIL] Could not schedule Drip Email - run this as Administrator
)

:: --- Daily Facebook Post (8:00 AM every day) ---
SCHTASKS /CREATE /TN "Enderun - Daily Facebook Post" ^
  /TR "\"%FOLDER%\run_daily_post.bat\"" ^
  /SC DAILY /ST 08:00 /F /RL HIGHEST
IF %ERRORLEVEL%==0 (
    echo  [OK] Daily Facebook Post scheduled at 8:00 AM
) ELSE (
    echo  [FAIL] Could not schedule Facebook Post - run this as Administrator
)

:: --- Weekly Analytics Report (8:00 AM every Monday) ---
SCHTASKS /CREATE /TN "Enderun - Weekly Analytics Report" ^
  /TR "\"%FOLDER%\run_weekly_report.bat\"" ^
  /SC WEEKLY /D MON /ST 08:00 /F /RL HIGHEST
IF %ERRORLEVEL%==0 (
    echo  [OK] Weekly Report scheduled every Monday at 8:00 AM
) ELSE (
    echo  [FAIL] Could not schedule Weekly Report - run this as Administrator
)

:: --- Daily Social Listening (7:50 AM every day) ---
SCHTASKS /CREATE /TN "Enderun - Social Listening" ^
  /TR "\"%FOLDER%\run_social_listening.bat\"" ^
  /SC DAILY /ST 07:50 /F /RL HIGHEST
IF %ERRORLEVEL%==0 (
    echo  [OK] Social Listening scheduled at 7:50 AM daily
) ELSE (
    echo  [FAIL] Could not schedule Social Listening - run this as Administrator
)

:: --- Weekly Campaign Preview (5:00 PM every Sunday) ---
SCHTASKS /CREATE /TN "Enderun - Weekly Campaign Preview" ^
  /TR "\"%FOLDER%\run_weekly_preview.bat\"" ^
  /SC WEEKLY /D SUN /ST 17:00 /F /RL HIGHEST
IF %ERRORLEVEL%==0 (
    echo  [OK] Weekly Campaign Preview scheduled every Sunday at 5:00 PM
) ELSE (
    echo  [FAIL] Could not schedule Weekly Campaign Preview - run this as Administrator
)

echo.
echo  ================================================
echo  Done! Verify in Task Scheduler (search: Task Scheduler)
echo  ================================================
echo.
echo  Scheduled tasks summary:
echo    7:50 AM daily  - Social Listening ^& Competitor Monitor
echo    8:00 AM daily  - Drip Email + Facebook Post
echo    8:00 AM Monday - Weekly Analytics Report
echo    5:00 PM Sunday - Weekly Campaign Preview PDF
echo  ================================================
echo.
pause
