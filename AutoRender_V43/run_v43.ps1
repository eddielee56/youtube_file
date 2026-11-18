param([ValidateSet('weekly','dry-run','status')][string]$Mode='weekly')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$logs=Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$python=(& py -3.12 -c 'import sys;print(sys.executable)') | Select-Object -First 1
if (-not $python) { throw 'Python 3.12 not found' }
& $python (Join-Path $PSScriptRoot 'autorender_v43.py') $Mode 2>&1 | Tee-Object -FilePath (Join-Path $logs ('v43_'+$Mode+'_'+$stamp+'.log'))
$code=$LASTEXITCODE
if ($null -ne $code -and $code -ne 0) { exit $code }
