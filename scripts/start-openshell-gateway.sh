#!/usr/bin/env bash
# Start OpenShell gateway from cache prefix (sandbox / container).
set -eu

CACHE="${AGENTS_OPENSHELL_DIR:-}"
if [ -z "$CACHE" ]; then
  echo "AGENTS_OPENSHELL_DIR required" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${OPENSHELL_PREFIX:-$CACHE/prefix}"
STATE="${OPENSHELL_STATE_DIR:-$CACHE/state}"
TLS="${OPENSHELL_TLS_DIR:-$STATE/tls}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$STATE/config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$STATE/data}"
export PATH="$PREFIX/usr/bin:$PATH"

GATEWAY_BIN="$PREFIX/usr/bin/openshell-gateway"
CLI="$PREFIX/usr/bin/openshell"
PID_FILE="$STATE/gateway.pid"
LOG="$STATE/gateway.log"
CONFIG="$STATE/gateway.toml"

if [ ! -x "$GATEWAY_BIN" ]; then
  echo "openshell-gateway missing; run install-openshell.sh first" >&2
  exit 1
fi

if [ ! -f "$TLS/server/tls.crt" ]; then
  echo "generating local mTLS + JWT bundle..."
  mkdir -p "$TLS"
  "$GATEWAY_BIN" generate-certs --output-dir "$TLS" --server-san localhost
fi

sed "s|{{TLS_DIR}}|$TLS|g" "$SCRIPT_DIR/../examples/gateway-sandbox.toml" >"$CONFIG"

bash "$SCRIPT_DIR/provision-openshell-mtls.sh"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
  sleep 1
fi

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "openshell-gateway already running (pid $(cat "$PID_FILE"))"
  exit 0
fi

nohup "$GATEWAY_BIN" --config "$CONFIG" >"$LOG" 2>&1 &
echo $! >"$PID_FILE"
sleep 2

for _ in $(seq 1 45); do
  if "$CLI" status 2>/dev/null | grep -q Version; then
    echo "openshell-gateway ready"
    exit 0
  fi
  "$CLI" gateway add "https://127.0.0.1:17670" --local --name openshell 2>/dev/null || true
  sleep 1
done

echo "openshell-gateway failed to become ready; see $LOG" >&2
tail -n 40 "$LOG" >&2 || true
exit 1
