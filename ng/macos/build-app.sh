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
# 发行版用独立 bundle id:与旧版 Tauri 应用(com.sj-tu.sjtu-monitor)并存时系统不会把两者混为一个应用;
# 数据目录由 BackendLocator 固定为 Application Support/com.sj-tu.sjtu-monitor,与 bundle id 无关,照常沿用。
if [[ "$CONFIG" == "release" ]]; then
    BUNDLE_ID="com.sj-tu.jiaowoxuan"
else
    BUNDLE_ID="com.sj-tu.jiaowoxuan.dev"
fi
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$REPO/package.json")"

cd "$HERE"
swift build -c "$CONFIG" --product JiaoWoXuan
BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"

APP="$HERE/build/$APP_NAME.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN_DIR/JiaoWoXuan" "$APP/Contents/MacOS/JiaoWoXuan"
# SwiftPM 把 LC_BUILD_VERSION 的 sdk 字段写成部署目标(14.0),系统会据此以旧版兼容外观运行,
# Liquid Glass 等新系统界面不会启用。改写为实际编译所用的 SDK 版本。
vtool -set-build-version macos 14.0 "$(xcrun --show-sdk-version)" -replace \
    -output "$APP/Contents/MacOS/JiaoWoXuan" "$APP/Contents/MacOS/JiaoWoXuan"
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

SIDECAR="${SJTU_BACKEND_DIR:-$REPO/src-tauri/resources/sjtu-backend}"
if [[ -x "$SIDECAR/sjtu-backend" ]]; then
    cp -R "$SIDECAR" "$APP/Contents/Resources/sjtu-backend"
    # 去掉 PyInstaller 产物里可能继承的隔离属性,避免签名后仍被 Gatekeeper 拦截内部 dylib
    xattr -cr "$APP/Contents/Resources/sjtu-backend" 2>/dev/null || true
    echo "已内置后端: $SIDECAR"
else
    echo "未找到冻结后端,.app 将使用源码后端(conda 环境 sjtu-monitor)"
fi

codesign --force --deep --sign - "$APP" >/dev/null
echo "$APP"
