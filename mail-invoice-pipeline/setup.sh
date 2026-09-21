#!/usr/bin/env bash
# mail-invoice-pipeline setup (macOS / Linux / Git Bash)
# Usage: bash setup.sh
# - npm install via npmmirror (inline flag only, global config untouched)
# - pip install via Tsinghua mirror (inline flag only)
# - creates config.yaml / ocr-config.json from examples if missing
set -e
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=== [1/4] Checking runtime tools ==="
command -v node >/dev/null || { echo "ERROR: node not found. Install Node.js >= 18."; exit 1; }
command -v npm  >/dev/null || { echo "ERROR: npm not found."; exit 1; }
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "ERROR: python3/python not found."; exit 1; }
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 18 ] || { echo "ERROR: Node.js >= 18 required."; exit 1; }
echo "node $(node --version), python: $PY"

echo
echo "=== [2/4] npm install (registry: $NPM_REGISTRY) ==="
npm install --registry="$NPM_REGISTRY"

echo
echo "=== [3/4] pip install (index: $PIP_INDEX) ==="
"$PY" -m pip install -r requirements.txt -i "$PIP_INDEX"

echo
echo "=== [4/4] Config templates ==="
if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
  echo "Created config.yaml from example -> EDIT IT: fill mailbox + IMAP auth code"
else
  echo "config.yaml already exists, skipped"
fi
if [ ! -f ocr-config.json ]; then
  cp ocr-config.example.json ocr-config.json
  echo "Created ocr-config.json from example -> EDIT IT if you want OCR fallback"
else
  echo "ocr-config.json already exists, skipped"
fi

echo
echo "SETUP DONE."
echo "Next: edit config.yaml (required), ocr-config.json (optional OCR)."
echo "Verify: node scripts/mail-scan-links.js   (lists invoice folder emails)"
