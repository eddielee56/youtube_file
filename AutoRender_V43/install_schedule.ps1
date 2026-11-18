# One separate task, does not touch V3.8 tasks; requires signed-in Windows user.
$ErrorActionPreference='Stop'
$zone=(Get-TimeZone).Id
if ($zone -notin @('Taipei Standard Time','China Standard Time')) { throw ('Expected UTC+08 Windows timezone; current: '+$zone) }
$root=$PSScriptRoot
$task='AutoRender_V43_WeeklyPreview'
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $root 'run_v43.ps1')+'" -Mode weekly') -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At '18:15'
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host ('Installed '+$task+' Fridays 18:15 local time. No YouTube upload.')
Write-Host 'Only operates while the current Windows user is logged on.'
