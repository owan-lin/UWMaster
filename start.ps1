$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $root 'data\server.log'
$errorLog = Join-Path $root 'data\server-error.log'
New-Item -ItemType Directory -Force (Join-Path $root 'data') | Out-Null

function Test-CourseMonitor {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8765/'
    return $response.StatusCode -eq 200 -and $response.Content -match 'UWMaster'
  } catch { return $false }
}

if (Test-CourseMonitor) { Start-Process 'http://127.0.0.1:8765'; Write-Host '课程面板已经在运行。'; exit 0 }

$candidates = @(
  'D:\DevTools\Python\pythoncore-3.14-64\python.exe',
  'D:\DevTools\Python\bin\python.exe',
  'python.exe', 'py.exe'
)
$python = $null
foreach ($candidate in $candidates) {
  try {
    if ($candidate -like '*\*') { if (Test-Path -LiteralPath $candidate) { $python = $candidate; break } }
    elseif (Get-Command $candidate -ErrorAction SilentlyContinue) { $python = $candidate; break }
  } catch {}
}
if (-not $python) { throw '找不到可用 Python 3。' }

if ($python -eq 'py.exe') { $args = @('-3', 'server.py') } else { $args = @('server.py') }
$process = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $errorLog -PassThru
for ($i=0; $i -lt 25; $i++) {
  Start-Sleep -Milliseconds 250
  if (Test-CourseMonitor) { Start-Process 'http://127.0.0.1:8765'; Write-Host '已启动：http://127.0.0.1:8765'; exit 0 }
  if ($process.HasExited) { break }
}
$tail = if (Test-Path $errorLog) { Get-Content $errorLog -Tail 12 | Out-String } else { '' }
throw "课程面板未能启动。错误日志：$errorLog`n$tail"
