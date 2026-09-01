#!/usr/bin/env bash
# Provision mTLS client material for openshell CLI + docker guest TLS paths.
set -eu

CACHE="${AGENTS_OPENSHELL_DIR:-}"
[ -n "$CACHE" ] || { echo "AGENTS_OPENSHELL_DIR required" >&2; exit 1; }

TLS="${OPENSHELL_TLS_DIR:-$CACHE/state/tls}"
CFG_MTLS="$CACHE/state/config/openshell/gateways/openshell/mtls"
mkdir -p "$CFG_MTLS"
cp "$TLS/ca.crt" "$CFG_MTLS/"
cp "$TLS/client/tls.crt" "$CFG_MTLS/"
cp "$TLS/client/tls.key" "$CFG_MTLS/"
echo "openshell mTLS client bundle: $CFG_MTLS"
