param([ValidateSet('gemini','azure')][string]$Name)
$ErrorActionPreference='Stop'
$path=Join-Path (Join-Path $env:LOCALAPPDATA 'AutoRenderV43') ($Name + '.dpapi')
if (-not (Test-Path -LiteralPath $path)) { exit 2 }
try {
    $encrypted=[System.IO.File]::ReadAllText($path,[System.Text.Encoding]::ASCII).Trim()
    $secure=ConvertTo-SecureString -String $encrypted -ErrorAction Stop
    $bstr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
} catch { exit 3 }
