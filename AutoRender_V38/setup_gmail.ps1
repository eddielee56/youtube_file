#requires -Version 5.1
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$addr=(Read-Host 'Enter your Gmail address for sending AND receiving').Trim()
if ($addr -notmatch '^[^\s@]+@(gmail|googlemail)\.com$') { throw 'Enter a valid Gmail address.' }
$secure=Read-Host 'Enter Google 16-character App Password (input hidden)' -AsSecureString
if ($secure.Length -ne 16) { throw 'Expected 16 characters. Remove any spaces and retry.' }
$secure | ConvertFrom-SecureString | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'gmail_app_password.dpapi') -Encoding ASCII
@{ address=$addr; enabled=$false; min_score=75 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'gmail_email.json') -Encoding UTF8
Write-Host 'Saved encrypted DPAPI secret for current Windows user. Email stays disabled until tested.'
