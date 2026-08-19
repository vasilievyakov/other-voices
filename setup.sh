#!/bin/bash
set -euo pipefail

# Call Recorder — Setup Script
# Run once: bash ~/call-recorder/setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Call Recorder Setup ==="
echo ""

# 1. Create directories
echo "[1/6] Creating directories..."
mkdir -p bin swift src data/recordings logs launchd

# 2. Create venv and install Python dependencies
echo "[2/6] Setting up Python venv..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet psutil
echo "  venv created, psutil installed"

# 3. Compile Swift binary (bare, owner's decision 2026-08-19 — see config.py).
# WARNING: rebuilding changes the code hash and macOS revokes the Screen
# Recording grant — re-grant bin/audio-capture after any rebuild.
APP_BIN="bin/audio-capture"
echo "[3/6] Compiling Swift audio-capture binary..."
swiftc swift/AudioCapture.swift -o "$APP_BIN" \
    -framework ScreenCaptureKit \
    -framework AVFoundation \
    -framework CoreMedia \
    -framework CoreAudio \
    -O \
    2>&1

if [ -f "$APP_BIN" ]; then
    echo "  $APP_BIN compiled successfully"
    chmod +x "$APP_BIN"
else
    echo "  ERROR: Compilation failed"
    exit 1
fi

echo "[3b/6] Compiling Swift call-signal binary..."
swiftc swift/CallSignal.swift -o bin/call-signal \
    -framework CoreAudio \
    -framework CoreMediaIO \
    -framework AppKit \
    -O \
    2>&1

if [ -f bin/call-signal ]; then
    echo "  bin/call-signal compiled successfully"
    chmod +x bin/call-signal
else
    echo "  ERROR: call-signal compilation failed"
    exit 1
fi

# Code-sign with a STABLE identifier so the identity does not drift on every
# rebuild. Previously the binary was signed with an auto-derived identifier
# (e.g. "audio-capture-new"); each rebuild changed it, macOS treated the binary
# as a brand-new app, and the Screen Recording (TCC) grant was silently revoked
# — which left system.wav missing from every recording.
#
# If an Apple Development identity is available, prefer it (stable Designated
# Requirement → the TCC grant survives rebuilds). Otherwise fall back to an
# ad-hoc signature with a fixed identifier.
#
# IMPORTANT (ad-hoc case): ad-hoc signing keeps the identifier stable but the
# code hash still changes on every rebuild, so macOS WILL forget the Screen
# Recording permission. After EACH rebuild you MUST re-grant it:
#   System Settings > Privacy & Security > Screen & System Audio Recording
# and re-add / re-enable bin/audio-capture, then restart the daemon.
CODESIGN_ID="com.vasiliev.audio-capture"
SIGNING_IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | grep -o '"Apple Development[^"]*"' | head -1 | tr -d '"')"
if [ -n "$SIGNING_IDENTITY" ]; then
    codesign --force --sign "$SIGNING_IDENTITY" --identifier "$CODESIGN_ID" "$APP_BIN"
    echo "  $APP_BIN signed with '$SIGNING_IDENTITY' (identifier $CODESIGN_ID)"
    echo "  Stable identity: the Screen Recording grant should survive rebuilds."
else
    codesign --force --sign - --identifier "$CODESIGN_ID" "$APP_BIN"
    echo "  $APP_BIN signed ad-hoc (identifier $CODESIGN_ID)"
    echo "  NOTE: no Apple Development identity found — ad-hoc signature changes"
    echo "  every rebuild. You MUST re-grant Screen Recording after each rebuild:"
    echo "  System Settings > Privacy & Security > Screen & System Audio Recording"
fi

# 4. Pull Ollama model
echo "[4/6] Pulling Ollama model (qwen3:14b)..."
if command -v ollama &>/dev/null; then
    if ollama list | grep -q "qwen3:14b"; then
        echo "  qwen3:14b already available"
    else
        echo "  Downloading qwen3:14b (~9 GB)..."
        ollama pull qwen3:14b
    fi
else
    echo "  WARNING: ollama not found. Install it first: https://ollama.com"
    echo "  Summarization will be skipped until Ollama is available."
fi

# 5. Install launchd agent
echo "[5/6] Installing launchd agent..."
PLIST_SRC="$SCRIPT_DIR/launchd/com.user.call-recorder.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.user.call-recorder.plist"

# Unload if already loaded
launchctl bootout gui/$(id -u) "$PLIST_DST" 2>/dev/null || true

cp "$PLIST_SRC" "$PLIST_DST"
sed -i '' "s|__HOME__|$HOME|g" "$PLIST_DST"
echo "  Plist copied to $PLIST_DST (with __HOME__ → $HOME)"

# 6. Verify mlx_whisper
echo "[6/6] Checking mlx_whisper..."
if [ -f "$HOME/.local/bin/mlx_whisper" ]; then
    echo "  mlx_whisper found at ~/.local/bin/mlx_whisper"
else
    echo "  WARNING: mlx_whisper not found at ~/.local/bin/mlx_whisper"
    echo "  Install: pipx install mlx-whisper"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Before starting, grant permissions in System Settings → Privacy & Security:"
echo "  1. Screen & System Audio Recording → add & enable bin/audio-capture"
echo "     (needed for system.wav; without it recordings are mic-only)"
echo "  2. Microphone → add & enable bin/audio-capture (or your terminal app)"
echo ""
echo "To start the daemon:"
echo "  launchctl bootstrap gui/\$(id -u) $PLIST_DST"
echo ""
echo "To run manually (for testing):"
echo "  cd ~/call-recorder && .venv/bin/python3 -m src.daemon"
echo ""
echo "To stop:"
echo "  launchctl bootout gui/\$(id -u) $PLIST_DST"
echo ""
echo "CLI usage:"
echo "  .venv/bin/python3 cli.py list"
echo "  .venv/bin/python3 cli.py search \"keyword\""
echo "  .venv/bin/python3 cli.py show 20260219_143000"
echo "  .venv/bin/python3 cli.py actions"
