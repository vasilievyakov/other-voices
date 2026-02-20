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

# 3. Compile Swift binary
echo "[3/6] Compiling Swift audio-capture binary..."
swiftc swift/AudioCapture.swift -o bin/audio-capture \
    -framework ScreenCaptureKit \
    -framework AVFoundation \
    -framework CoreMedia \
    -framework CoreAudio \
    -O \
    2>&1

if [ -f bin/audio-capture ]; then
    echo "  bin/audio-capture compiled successfully"
    chmod +x bin/audio-capture
else
    echo "  ERROR: Compilation failed"
    exit 1
fi

# 4. Pull Ollama model
echo "[4/6] Pulling Ollama model (qwen2.5:7b)..."
if command -v ollama &>/dev/null; then
    if ollama list | grep -q "qwen2.5:7b"; then
        echo "  qwen2.5:7b already available"
    else
        echo "  Downloading qwen2.5:7b (~4.7 GB)..."
        ollama pull qwen2.5:7b
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
echo "  1. Screen Recording → add Terminal (or your terminal app)"
echo "  2. Microphone → add Terminal (or your terminal app)"
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
