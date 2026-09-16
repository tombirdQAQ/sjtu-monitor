#!/usr/bin/env bash
# 构建 交我选 ng 的 macOS .app。
#
#   ng/macos/build-app.sh            # release 构建,输出 ng/macos/build/交我选.app
#   ng/macos/build-app.sh debug      # debug 构建
#
# 若 src-tauri/resources/sjtu-backend/ 下有 PyInstaller 冻结的后端(CI 发行构建产物),
# 会一并放进 Contents/Resources/sjtu-backend,得到可独立运行的发行版;否则 .app
# 运行时回落到源码后端(需要 SJTU_MONITOR_ROOT 或从仓库内启动)。
set -euo pipefail

CONFIG="${1:-release}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
APP_NAME="交我选"
BUNDLE_ID="com.sj-tu.sjtu-monitor.ng"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$REPO/package.json")"

cd "$HERE"
swift build -c "$CONFIG" --product JiaoWoXuan
BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"

APP="$HERE/build/$APP_NAME.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN_DIR/JiaoWoXuan" "$APP/Contents/MacOS/JiaoWoXuan"
cp "$REPO/src-tauri/icons/icon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key><string>zh-Hans</string>
    <key>CFBundleDisplayName</key><string>$APP_NAME</string>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleExecutable</key><string>JiaoWoXuan</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSSupportsAutomaticTermination</key><false/>
</dict>
</plist>
PLIST

SIDECAR="$REPO/src-tauri/resources/sjtu-backend"
if [[ -x "$SIDECAR/sjtu-backend" ]]; then
    cp -R "$SIDECAR" "$APP/Contents/Resources/sjtu-backend"
    echo "已内置后端: $SIDECAR"
else
    echo "未找到冻结后端,.app 将使用源码后端(conda 环境 sjtu-monitor)"
fi

codesign --force --deep --sign - "$APP" >/dev/null
echo "$APP"
