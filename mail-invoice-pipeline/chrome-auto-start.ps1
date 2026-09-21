# Launch the dedicated Chrome used by scripts/mail-download-browser.js (Windows)
# Isolated profile under <skill>\chrome-auto, debug port 9222. Does NOT touch your main Chrome.
# Usage:  powershell -ExecutionPolicy Bypass -File chrome-auto-start.ps1 [-Port 9222]
param([int]$Port = 9222)

$root = $PSScriptRoot
$dataDir = Join-Path $root "chrome-auto"

# Already listening? Then the dedicated Chrome is up.
try {
  $tcp = New-Object System.Net.Sockets.TcpClient
  $tcp.Connect("127.0.0.1", $Port)
  $tcp.Close()
  Write-Host "Port $Port already listening - dedicated Chrome is running. (http://127.0.0.1:$Port)"
  exit 0
} catch { }

$candidates = @(
  (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
  (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
  (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe"),
  (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
  (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe")
)
$exe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $exe) {
  Write-Host "ERROR: Chrome/Edge executable not found. Install Chrome or set CHROME_EXE."
  exit 1
}
if ($env:CHROME_EXE -and (Test-Path $env:CHROME_EXE)) { $exe = $env:CHROME_EXE }

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Start-Process -FilePath $exe -ArgumentList @(
  "--remote-debugging-port=$Port",
  "--user-data-dir=$dataDir",
  "--no-first-run",
  "--no-default-browser-check",
  "about:blank"
)
Write-Host "Dedicated Chrome started: $exe"
Write-Host "Profile: $dataDir | CDP: http://127.0.0.1:$Port"
Write-Host "Now run: node scripts/mail-download-browser.js"
