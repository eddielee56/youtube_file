$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$run=Join-Path $root 'run_v38.ps1'
$new=Join-Path $root 'run_v38_gmail.ps1'
if (!(Test-Path $new)) { throw 'Missing run_v38_gmail.ps1' }
if (!(Test-Path $run)) { throw 'Missing run_v38.ps1' }
$backup=Join-Path $root 'run_v38.before_gmail.ps1'
if (!(Test-Path $backup)) { Copy-Item -LiteralPath $run -Destination $backup }
Copy-Item -LiteralPath $new -Destination $run -Force
Write-Host 'Installed Gmail runner; previous runner backed up. Scheduled tasks still point to run_v38.ps1.'
