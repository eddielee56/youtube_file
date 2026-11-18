# Run interactively in PowerShell 5.1 as the signed-in user. No admin required for user tasks.
param([switch]$Remove)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$tasks=@(
 @{Name='AutoRender_V38_Daily'; At='08:30'; Days=$null; Mode='daily'},
 @{Name='AutoRender_V38_Weekly'; At='18:00'; Days='Friday'; Mode='weekly'}
)
if ($Remove) {
 foreach ($t in $tasks) { Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue }
 Write-Host '排程已移除'; exit 0
}
$zone=(Get-TimeZone).Id
Write-Host "目前 Windows 時區：$zone（請確認為台灣時間 UTC+08）"
if ($zone -notin @('Taipei Standard Time','China Standard Time')) {
 throw 'Windows 時區不是預期的 UTC+08。請先確認時區再安裝排程。'
}
$principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
foreach ($t in $tasks) {
 $arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $root 'run_v38.ps1') + '" -Mode ' + $t.Mode
 $act=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $root
 if ($t.Days) { $trig=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At $t.At }
 else { $trig=New-ScheduledTaskTrigger -Daily -At $t.At }
 Register-ScheduledTask -TaskName $t.Name -Action $act -Trigger $trig -Principal $principal -Settings $settings -Force | Out-Null
 Write-Host ('已建立 '+$t.Name+'，'+$t.At)
}
Write-Host '注意：排程需登入 Windows，睡眠或關機時無法即時執行；本排程不寄信、不製片、不上傳 YouTube。'
