@echo off
echo ================================================
echo  Enderun - Enable "Run if Missed" on All Tasks
echo  RIGHT-CLICK this file > Run as Administrator
echo ================================================
echo.

powershell -Command " ^
foreach ($name in @('Enderun - Daily Drip Email','Enderun - Daily Facebook Post','Enderun - Weekly Analytics Report','Enderun - Social Listening','Enderun - Weekly Campaign Preview')) { ^
  try { ^
    $t = Get-ScheduledTask -TaskName $name -ErrorAction Stop; ^
    $t.Settings.StartWhenAvailable = $true; ^
    Set-ScheduledTask -InputObject $t | Out-Null; ^
    Write-Host '[OK]' $name ^
  } catch { ^
    Write-Host '[FAIL]' $name '-' $_ ^
  } ^
} ^
"

echo.
echo ================================================
echo  Done! Tasks will now auto-run when laptop wakes
echo  up even if the scheduled time was missed.
echo ================================================
echo.
pause
