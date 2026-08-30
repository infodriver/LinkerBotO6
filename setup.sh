#!/usr/bin/env bash
# LinkerBot O6 SDK — environment setup + self-test.
set -euo pipefail
cd "$(dirname "$0")"

echo "== LinkerBot O6 SDK setup =="

# 1. Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.9+ first." >&2
  exit 1
fi
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "python3: $PYVER"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' \
  || { echo "ERROR: Python 3.9+ required (found $PYVER)." >&2; exit 1; }

# 2. libusb
if python3 -c 'import ctypes.util; exit(0 if ctypes.util.find_library("usb-1.0") else 1)' 2>/dev/null; then
  echo "libusb: found"
else
  echo "libusb: not found — installing..."
  if [ "$(uname)" = "Darwin" ]; then
    if ! command -v brew >/dev/null 2>&1; then
      echo "ERROR: Homebrew required on macOS: https://brew.sh" >&2; exit 1
    fi
    brew install libusb
  elif [ -f /etc/debian_version ] || [ -f /etc/ubuntu_version ] 2>/dev/null; then
    sudo apt-get update && sudo apt-get install -y libusb-1.0-0-dev
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y libusbx-devel
  else
    echo "ERROR: install libusb 1.0 manually (https://libusb.info), then re-run." >&2
    exit 1
  fi
fi

# 3. Self-test
echo
echo "== Self-test: probing the hand =="
python3 -m linkerbot_o6.cli probe || true

echo
echo "Done. Commands:"
echo "  python3 -m linkerbot_o6.cli probe            # health check"
echo "  python3 -m linkerbot_o6.cli move --preset open"
echo "  python3 -m linkerbot_o6.web                  # web panel @ http://127.0.0.1:8080"
