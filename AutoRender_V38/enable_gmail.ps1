$ErrorActionPreference='Stop'
$path=Join-Path $PSScriptRoot 'gmail_email.json'
if (!(Test-Path $path)) { throw 'Run setup_gmail.ps1 first.' }
$report=Join-Path $PSScriptRoot 'output\gmail_last_delivery.json'
if (!(Test-Path $report)) { throw 'First run email test successfully.' }
$r=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
if ($r.status -ne 'SENT' -or $r.action -ne 'test') { throw 'Run a successful Gmail test first.' }
$c=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
$c.enabled=$true
$c | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding UTF8
Write-Host 'Gmail notification ENABLED. New high-priority unverified leads only, once per event key.'
