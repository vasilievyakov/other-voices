#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Building Other Voices..."
swift build -c release 2>&1

BUILD_DIR=".build/release"
APP_NAME="Other Voices"
APP_DIR="${APP_NAME}.app/Contents/MacOS"
RES_DIR="${APP_NAME}.app/Contents/Resources"

mkdir -p "$APP_DIR" "$RES_DIR"
cp "$BUILD_DIR/OtherVoices" "$APP_DIR/"

# Generate icon if script exists
if [ -f "icon/generate_icon.py" ]; then
    echo "Generating app icon..."
    python3 icon/generate_icon.py
    if [ -f "icon/AppIcon.icns" ]; then
        cp "icon/AppIcon.icns" "$RES_DIR/"
    fi
fi

# Create Info.plist
cat > "${APP_NAME}.app/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Other Voices</string>
    <key>CFBundleDisplayName</key>
    <string>Other Voices</string>
    <key>CFBundleIdentifier</key>
    <string>com.user.other-voices</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>OtherVoices</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Other Voices needs microphone access for audio playback.</string>
</dict>
</plist>
EOF

# Remove quarantine to avoid App Translocation
xattr -dr com.apple.quarantine "${APP_NAME}.app" 2>/dev/null || true

echo ""
echo "Built: $(pwd)/${APP_NAME}.app"
echo "Run with: open \"${APP_NAME}.app\""
