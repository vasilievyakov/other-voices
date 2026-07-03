#!/bin/bash
# Restart the Call Recorder ("Other Voices") launchd daemon.
#
# Run this manually after:
#   - rebuilding bin/audio-capture (the daemon caches nothing, but a fresh
#     binary + re-granted Screen Recording permission only take effect on a
#     restart), or
#   - re-granting Screen & System Audio Recording in System Settings.
#
# Usage: bash ~/call-recorder/restart-daemon.sh
set -uo pipefail

LABEL="com.user.call-recorder"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

if [ ! -f "$PLIST" ]; then
    echo "ERROR: plist not found at $PLIST"
    echo "Run setup.sh first to install the launchd agent."
    exit 1
fi

echo "Restarting $LABEL ..."

# --- Unload (modern bootout, fallback to legacy unload) ---
if launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null; then
    echo "  booted out $DOMAIN"
else
    echo "  bootout failed or not loaded; trying legacy unload"
    launchctl unload "$PLIST" 2>/dev/null || true
fi

# --- Load (modern bootstrap, fallback to legacy load) ---
if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
    echo "  bootstrapped $DOMAIN"
else
    echo "  bootstrap failed; trying legacy load"
    launchctl load "$PLIST"
fi

# --- Kick it running now (RunAtLoad already does this, but be explicit) ---
launchctl kickstart -k "${DOMAIN}/${LABEL}" 2>/dev/null || true

echo "Done. Check status with:"
echo "  launchctl print ${DOMAIN}/${LABEL} | grep -E 'state|pid'"
echo "  tail -f ~/call-recorder/logs/call-recorder.log"
