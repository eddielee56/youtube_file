# AutoRender V3.8 scheduler installer - ASCII only for Windows PowerShell 5.1
# Run from PowerShell as the Windows user who will run the tasks.
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runner = Join-Path $root 'run_v38.ps1'
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Missing run_v38.ps1 in $root"
}
$tz = (Get-TimeZone).Id
if ($tz -notin @('Taipei Standard Time', 'China Standard Time')) {
    throw "Windows time zone is '$tz'. Set it to UTC+08:00 before installing."
}
$tasks = @(
    @{ Name = 'AutoRender_V38_Daily'; Time = '08:30'; Mode = 'daily'; Frequency = 'Daily' },
    @{ Name = 'AutoRender_V38_Weekly'; Time = '18:00'; Mode = 'weekly'; Frequency = 'Weekly' }
)
if ($Remove) {
    foreach ($t in $tasks) {
        Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed: $($t.Name)"
    }
    exit 0
}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
foreach ($t in $tasks) {
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '" -Mode ' + $t.Mode
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $root
    if ($t.Frequency -eq 'Weekly') {
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At $t.Time
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $t.Time
    }
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Installed: $($t.Name) at $($t.Time) [$($t.Frequency)]"
}
Write-Host 'Tasks installed. They run while this Windows user is logged on.'
Write-Host 'Check with: Get-ScheduledTask -TaskName "AutoRender_V38_*"'
