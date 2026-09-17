#!/usr/bin/env bash
# 打包 交我选 macOS 发行版 DMG(Apple Silicon,未做 Developer ID 签名与公证)。
#
#   python -m PyInstaller sjtu-backend.spec --distpath src-tauri/resources --noconfirm
#   ng/macos/package-dmg.sh
#
# 输出 build/macos/JiaoWoXuan-<版本>-macos-arm64.dmg
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$REPO/package.json")"

export SJTU_BACKEND_DIR="${SJTU_BACKEND_DIR:-$REPO/src-tauri/resources/sjtu-backend}"
if [[ ! -x "$SJTU_BACKEND_DIR/sjtu-backend" ]]; then
    echo "未找到冻结后端 $SJTU_BACKEND_DIR/sjtu-backend,请先运行 PyInstaller" >&2
    exit 1
fi

bash "$HERE/build-app.sh" release
APP="$HERE/build/交我选.app"
if [[ ! -x "$APP/Contents/Resources/sjtu-backend/sjtu-backend" ]]; then
    echo ".app 内缺少后端" >&2
    exit 1
fi

OUT_DIR="$REPO/build/macos"
STAGE="$OUT_DIR/dmg-stage"
DMG="$OUT_DIR/JiaoWoXuan-$VERSION-macos-arm64.dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "交我选 $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null
rm -rf "$STAGE"
echo "$DMG"
