# Called by Python; do not run interactively or echo output in screenshots.
$ErrorActionPreference='Stop'
$file=Join-Path $PSScriptRoot 'gmail_app_password.dpapi'
$secure=(Get-Content -LiteralPath $file -Raw).Trim() | ConvertTo-SecureString
$bstr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { [Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
