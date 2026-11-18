param([ValidateSet('daily','weekly','prepare-review','status')][string]$Mode='status')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$logDir=Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$arguments=@('-3.12', (Join-Path $PSScriptRoot 'autorender_v38.py'), $Mode)
# Old V3.8 SMTP is disabled; the DPAPI-based notifier runs separately below.
if ($Mode -eq 'daily') { $arguments+= '--no-email' }
& py @arguments 2>&1 | Tee-Object -FilePath (Join-Path $logDir "${Mode}_${stamp}.log")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Mode -eq 'daily') {
  & py -3.12 (Join-Path $PSScriptRoot 'autorender_email.py') notify 2>&1 | Tee-Object -FilePath (Join-Path $logDir "mail_${stamp}.log")
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
