#!/usr/bin/env bash
# 在 macOS 上构建便携包 / .app /（可选）.dmg
# 用法：
#   chmod +x scripts/build-installer-mac.sh
#   ./scripts/build-installer-mac.sh
#   ./scripts/build-installer-mac.sh --version 0.1.1
set -euo pipefail

APP_VERSION="0.1.0"
PY_TAG="3.12.8"
# python-build-standalone 发布日期标签（若 404 请到 GitHub Releases 改新日期）
STANDALONE_DATE="20250317"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) APP_VERSION="$2"; shift 2 ;;
    --py) PY_TAG="$2"; shift 2 ;;
    --date) STANDALONE_DATE="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/packaging"
CACHE="$PKG/cache"
PAYLOAD="$PKG/payload-mac"
DIST="$ROOT/dist"
RUNTIME="$PAYLOAD/runtime"
APP_NAME="买入时机"

mkdir -p "$CACHE" "$DIST"
rm -rf "$PAYLOAD"
mkdir -p "$PAYLOAD"

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) TARGET="aarch64-apple-darwin" ;;
  x86_64) TARGET="x86_64-apple-darwin" ;;
  *) echo "不支持的架构: $ARCH"; exit 1 ;;
esac

TARBALL="cpython-${PY_TAG}+${STANDALONE_DATE}-${TARGET}-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${STANDALONE_DATE}/${TARBALL}"
TAR_PATH="$CACHE/$TARBALL"

echo "==> 下载独立 Python ($TARGET)"
if [[ ! -f "$TAR_PATH" ]]; then
  curl -L --fail -o "$TAR_PATH" "$URL"
fi

echo "==> 解压 runtime"
mkdir -p "$RUNTIME"
# install_only 包顶层通常为 python/
tar -xzf "$TAR_PATH" -C "$RUNTIME"
if [[ -d "$RUNTIME/python" ]]; then
  # 把 python/* 提到 runtime/
  shopt -s dotglob
  mv "$RUNTIME/python"/* "$RUNTIME/"
  rmdir "$RUNTIME/python"
  shopt -u dotglob
fi

PY="$RUNTIME/bin/python3"
if [[ ! -x "$PY" ]]; then
  echo "未找到 $PY"
  exit 1
fi

echo "==> 安装运行时依赖"
REQ="$ROOT/requirements-runtime.txt"
[[ -f "$REQ" ]] || REQ="$ROOT/requirements.txt"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r "$REQ"

echo "==> 复制应用"
cp -R "$ROOT/app" "$PAYLOAD/app"
find "$PAYLOAD/app" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
mkdir -p "$PAYLOAD/scripts"
cp "$ROOT/scripts/launcher.py" "$PAYLOAD/scripts/launcher.py"
cp "$PKG/Start.command" "$PAYLOAD/Start.command"
chmod +x "$PAYLOAD/Start.command"
cp "$REQ" "$PAYLOAD/requirements.txt"
mkdir -p "$PAYLOAD/docs"
[[ -f "$ROOT/docs/安装与使用.md" ]] && cp "$ROOT/docs/安装与使用.md" "$PAYLOAD/docs/"

PORTABLE_ZIP="$DIST/${APP_NAME}-mac-portable-${APP_VERSION}-${ARCH}.zip"
echo "==> 便携 zip: $PORTABLE_ZIP"
rm -f "$PORTABLE_ZIP"
(
  cd "$PAYLOAD"
  zip -qry "$PORTABLE_ZIP" .
)

# .app bundle
APP_DIR="$DIST/${APP_NAME}.app"
echo "==> 生成 $APP_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$PKG/macos/Info.plist" "$APP_DIR/Contents/Info.plist"
# 写入版本
/usr/bin/sed -i '' "s#<string>0.1.0</string>#<string>${APP_VERSION}</string>#g" "$APP_DIR/Contents/Info.plist" || true
cp "$PKG/macos/AppExec.sh" "$APP_DIR/Contents/MacOS/${APP_NAME}"
chmod +x "$APP_DIR/Contents/MacOS/${APP_NAME}"
rsync -a "$PAYLOAD/" "$APP_DIR/Contents/Resources/"

DMG="$DIST/${APP_NAME}-mac-${APP_VERSION}-${ARCH}.dmg"
echo "==> DMG: $DMG"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$APP_DIR" -ov -format UDZO "$DMG"

echo
echo "完成："
echo "  $PORTABLE_ZIP"
echo "  $APP_DIR"
echo "  $DMG"
echo "首次在别的 Mac 打开若提示损坏/无法验证：右键打开，或 xattr -cr 路径"
