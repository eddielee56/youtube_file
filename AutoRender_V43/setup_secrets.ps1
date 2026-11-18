# Store API keys with Windows DPAPI in LOCALAPPDATA, scoped to the signed-in user.
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'AutoRenderV43'
New-Item -Path $dir -ItemType Directory -Force | Out-Null
foreach ($entry in @(@{Name='gemini'; Prompt='Gemini API key'}, @{Name='azure'; Prompt='Azure Speech API key'})) {
    $secret = Read-Host ($entry.Prompt + ' (hidden)') -AsSecureString
    if ($secret.Length -eq 0) { throw ('Empty secret: ' + $entry.Name) }
    $cipher = ConvertFrom-SecureString -SecureString $secret
    [System.IO.File]::WriteAllText((Join-Path $dir ($entry.Name + '.dpapi')), $cipher, [System.Text.Encoding]::ASCII)
    Remove-Variable secret,cipher -ErrorAction SilentlyContinue
    Write-Host ('Saved encrypted credential: ' + $entry.Name)
}
Write-Host 'Credentials stored outside OneDrive. Scheduled runner uses the same signed-in Windows account.'
