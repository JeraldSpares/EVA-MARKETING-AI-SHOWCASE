@echo off
echo ================================================
echo  Enderun - Add "On Logon" Trigger to All Tasks
echo  RIGHT-CLICK this file > Run as Administrator
echo ================================================
echo.

powershell -Command " ^
$tasks = @( ^
  'Enderun - Daily Drip Email', ^
  'Enderun - Daily Facebook Post', ^
  'Enderun - Weekly Analytics Report', ^
  'Enderun - Social Listening', ^
  'Enderun - Weekly Campaign Preview' ^
); ^
foreach ($name in $tasks) { ^
  try { ^
    $t = Get-ScheduledTask -TaskName $name -ErrorAction Stop; ^
    $logon = New-ScheduledTaskTrigger -AtLogOn; ^
    $triggers = $t.Triggers + $logon; ^
    Set-ScheduledTask -TaskName $name -Trigger $triggers | Out-Null; ^
    Write-Host '[OK] Logon trigger added:' $name ^
  } catch { ^
    Write-Host '[FAIL]' $name '-' $_ ^
  } ^
} ^
"

echo.
echo ================================================
echo  Done! Every time you log in to Windows,
echo  all missed tasks will run automatically.
echo ================================================
echo.
pause
