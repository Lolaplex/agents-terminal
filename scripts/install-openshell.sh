#!/usr/bin/env bash
# Install OpenShell CLI + gateway into a cache prefix (no system dpkg).
# Used by agents-sandbox and future Docker/install.sh — never touches ~/.agents.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${AGENTS_OPENSHELL_DIR:-}"
if [ -z "$CACHE" ]; then
  if [ -n "${AGENTS_SANDBOX_CACHE:-}" ]; then
    CACHE="${AGENTS_SANDBOX_CACHE}/openshell"
  else
    CACHE="${ROOT}/.cache/openshell"
  fi
fi

PREFIX="${OPENSHELL_PREFIX:-$CACHE/prefix}"
STATE="${OPENSHELL_STATE_DIR:-$CACHE/state}"
VERSION="${OPENSHELL_VERSION:-}"
REPO="NVIDIA/OpenShell"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) DEB_ARCH="amd64" ;;
  aarch64|arm64) DEB_ARCH="arm64" ;;
  *) echo "openshell: unsupported arch $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$PREFIX" "$STATE"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$STATE/config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$STATE/data}"
export PATH="$PREFIX/usr/bin:$PREFIX/usr/local/bin:$PATH"

if [ -x "$PREFIX/usr/bin/openshell" ]; then
  echo "openshell: already installed at $PREFIX/usr/bin/openshell"
  exit 0
fi

if [ -z "$VERSION" ]; then
  VERSION="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | sed -n 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/p' | head -1)"
fi
[ -n "$VERSION" ] || { echo "openshell: could not resolve release version" >&2; exit 1; }

DEB="openshell_${VERSION}-1_${DEB_ARCH}.deb"
URL="https://github.com/${REPO}/releases/download/v${VERSION}/${DEB}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "openshell: downloading ${DEB}..."
curl -fLsS --retry 3 -o "$TMP/$DEB" "$URL"
dpkg-deb -x "$TMP/$DEB" "$PREFIX"

if [ ! -x "$PREFIX/usr/bin/openshell" ]; then
  echo "openshell: openshell binary missing after extract" >&2
  exit 1
fi

echo "openshell: extracted to $PREFIX"
echo "export OPENSHELL_PREFIX=$PREFIX"
echo "export OPENSHELL_STATE_DIR=$STATE"
echo "export PATH=$PREFIX/usr/bin:\$PATH"
