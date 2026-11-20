param([ValidateSet('weekly','dry-run','status')][string]$Mode='weekly')
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$configPath=Join-Path $PSScriptRoot 'runtime_config.json'
$python=$null
if (Test-Path -LiteralPath $configPath) {
    $config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $python=$config.python_executable
}
if (-not $python) { $python=(& py -3.12 -c 'import sys;print(sys.executable)') | Select-Object -First 1 }
if (-not $python -or -not (Test-Path -LiteralPath $python)) { throw 'Python 3.12 not found; configure python_executable in runtime_config.json' }
$runtime=(& $python -B -c 'import sys;sys.path.insert(0,sys.argv[1]);import autorender_v43;print(autorender_v43.ROOT)' $PSScriptRoot) | Select-Object -Last 1
if ($LASTEXITCODE -ne 0 -or -not $runtime) { throw 'Cannot resolve V4.3 runtime project' }
Set-Location -LiteralPath $runtime
$logs=Join-Path $runtime 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
Write-Host ('V4.3 runtime: '+$runtime)
& $python -B (Join-Path $runtime 'autorender_v43.py') $Mode 2>&1 | Tee-Object -FilePath (Join-Path $logs ('v43_'+$Mode+'_'+$stamp+'.log'))
$code=$LASTEXITCODE
if ($null -ne $code -and $code -ne 0) { exit $code }
