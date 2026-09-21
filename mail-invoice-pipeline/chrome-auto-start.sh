#!/usr/bin/env bash
# Launch the dedicated Chrome used by scripts/mail-download-browser.js (macOS/Linux/Git Bash)
# Isolated profile under <skill>/chrome-auto, debug port 9222. Does NOT touch your main Chrome.
# Usage: bash chrome-auto-start.sh [port]
PORT="${1:-9222}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$ROOT/chrome-auto"

# Already listening?
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  exec 3>&- 3<&-
  echo "Port $PORT already listening - dedicated Chrome is running."
  exit 0
fi

EXE="${CHROME_EXE:-}"
if [ -z "$EXE" ]; then
  case "$(uname -s)" in
    Darwin)
      EXE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      [ -x "$EXE" ] || EXE="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
      ;;
    *)
      EXE="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium || command -v chromium-browser || command -v microsoft-edge || true)"
      ;;
  esac
fi
if [ -z "$EXE" ] || [ ! -e "$EXE" ]; then
  echo "ERROR: Chrome/Chromium/Edge not found. Install one, or export CHROME_EXE=/path/to/chrome."
  exit 1
fi

mkdir -p "$DATA_DIR"
"$EXE" --remote-debugging-port="$PORT" --user-data-dir="$DATA_DIR" \
  --no-first-run --no-default-browser-check about:blank >/dev/null 2>&1 &
echo "Dedicated Chrome started: $EXE"
echo "Profile: $DATA_DIR | CDP: http://127.0.0.1:$PORT"
echo "Now run: node scripts/mail-download-browser.js"
