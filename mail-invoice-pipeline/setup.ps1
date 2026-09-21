# mail-invoice-pipeline setup (Windows PowerShell 5.1 compatible, ASCII-only)
# Usage:  powershell -ExecutionPolicy Bypass -File setup.ps1
# What it does:
#   1. Check Node.js / npm / Python / pip
#   2. npm install (npmmirror registry, inline flag only - global config untouched)
#   3. pip install -r requirements.txt (Tsinghua mirror, inline flag only)
#   4. Create config.yaml / ocr-config.json from examples if missing
param(
  [string]$NpmRegistry = "https://registry.npmmirror.com",
  [string]$PipIndex = "https://pypi.tuna.tsinghua.edu.cn/simple"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Check-Cmd($name) {
  $c = Get-Command $name -ErrorAction SilentlyContinue
  if (-not $c) { throw "Required tool not found in PATH: $name" }
  return $c.Source
}

Write-Host "=== [1/4] Checking runtime tools ==="
$node = Check-Cmd "node"
$npm = Check-Cmd "npm"
$py = $null
foreach ($p in @("python", "py", "python3")) {
  $c = Get-Command $p -ErrorAction SilentlyContinue
  if ($c) { $py = $p; break }
}
if (-not $py) { throw "Python not found (tried: python / py / python3)" }

$nodeVer = (& node --version)
Write-Host ("node {0} ({1})" -f $nodeVer, $node)
$major = [int]($nodeVer -replace '^v(\d+)\..*','$1')
if ($major -lt 18) { throw "Node.js >= 18 required (found $nodeVer). Global fetch / imapflow / puppeteer-core need it." }
Write-Host ("python via '{0}'" -f $py)

Write-Host ""
Write-Host "=== [2/4] npm install (registry: $NpmRegistry) ==="
& npm install --registry=$NpmRegistry
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }

Write-Host ""
Write-Host "=== [3/4] pip install (index: $PipIndex) ==="
& $py -m pip install -r requirements.txt -i $PipIndex
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host ""
Write-Host "=== [4/4] Config templates ==="
if (-not (Test-Path (Join-Path $root "config.yaml"))) {
  Copy-Item (Join-Path $root "config.example.yaml") (Join-Path $root "config.yaml")
  Write-Host "Created config.yaml from example -> EDIT IT: fill mailbox + IMAP auth code"
} else {
  Write-Host "config.yaml already exists, skipped"
}
if (-not (Test-Path (Join-Path $root "ocr-config.json"))) {
  Copy-Item (Join-Path $root "ocr-config.example.json") (Join-Path $root "ocr-config.json")
  Write-Host "Created ocr-config.json from example -> EDIT IT if you want OCR fallback"
} else {
  Write-Host "ocr-config.json already exists, skipped"
}

Write-Host ""
Write-Host "SETUP DONE."
Write-Host "Next: edit config.yaml (required), ocr-config.json (optional OCR)."
Write-Host "Verify: node scripts/mail-scan-links.js   (lists invoice folder emails)"
