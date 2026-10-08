$ErrorActionPreference = 'Stop'
$retrievalRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$retrievalPackages = Join-Path $retrievalRoot 'work\runtime-packages'
New-Item -ItemType Directory -Force -Path $retrievalPackages | Out-Null
python -m pip install --target $retrievalPackages 'playwright==1.63.0' 'pypdf==6.19.0' tzdata
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Ready. Restart UWMaster, then connect the course browser. Microsoft Edge is required.'
