$ErrorActionPreference = 'Stop'
$gmailRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$gmailPackages = Join-Path $gmailRoot 'work\runtime-packages'
New-Item -ItemType Directory -Force -Path $gmailPackages | Out-Null
$gmailPython = 'D:\DevTools\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path -LiteralPath $gmailPython)) { $gmailPython = 'python' }
& $gmailPython -m pip install --target $gmailPackages --upgrade 'google-auth-oauthlib==1.5.0'
if ($LASTEXITCODE -ne 0) { throw 'Gmail dependency installation failed.' }
Write-Host 'Restart UWMaster, then configure Gmail on the Gmail settings page.'
