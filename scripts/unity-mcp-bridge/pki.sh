#!/usr/bin/env bash
# Runs inside WSL. Ensures this machine's private Unity MCP CA exists and that
# the bridge's leaf certificate covers the current Windows-side WSL address.
#
#   pki.sh <wsl-gateway-ip> <output-dir>
#
# The CA and its key live only in $PKI_DIR (mode 700) and never leave this
# machine. The leaf chain + key are copied to <output-dir> for the Windows TLS
# proxy. Prints "CA=<path>" and "LEAF=reissued|unchanged".
set -euo pipefail

IP="${1:?usage: pki.sh <wsl-gateway-ip> <output-dir>}"
OUT="${2:?usage: pki.sh <wsl-gateway-ip> <output-dir>}"
PKI_DIR="${SKETCHSCAPE_UNITY_MCP_PKI_DIR:-$HOME/.config/sketchscape/unity-mcp-pki}"
HOSTNAME_SAN="unity-mcp.private"

mkdir -p "$PKI_DIR"
chmod 700 "$PKI_DIR"
cd "$PKI_DIR"

if [ ! -f ca.pem ] || [ ! -f ca.key ]; then
  # NemoClaw only imports certificates with basicConstraints CA:TRUE, so the
  # bridge needs a real (tiny) CA, not a self-signed leaf.
  openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
    -keyout ca.key -out ca.pem \
    -subj "/CN=SketchScape Local Unity MCP CA ($(hostname))" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  chmod 600 ca.key
  chmod 644 ca.pem
  rm -f leaf.crt leaf.key
fi

leaf_matches() {
  [ -f leaf.crt ] && [ -f leaf.key ] || return 1
  openssl verify -CAfile ca.pem leaf.crt >/dev/null 2>&1 || return 1
  openssl x509 -in leaf.crt -noout -checkend 2592000 >/dev/null || return 1
  openssl x509 -in leaf.crt -noout -ext subjectAltName 2>/dev/null \
    | grep -q "IP Address:${IP}\b"
}

if leaf_matches; then
  state=unchanged
else
  openssl req -newkey rsa:2048 -nodes -keyout leaf.key -out leaf.csr \
    -subj "/CN=${HOSTNAME_SAN}" 2>/dev/null
  printf '%s\n' \
    "basicConstraints=CA:FALSE" \
    "keyUsage=critical,digitalSignature,keyEncipherment" \
    "extendedKeyUsage=serverAuth" \
    "subjectAltName=DNS:${HOSTNAME_SAN},IP:${IP}" > leaf.ext
  openssl x509 -req -in leaf.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
    -days 825 -sha256 -extfile leaf.ext -out leaf.crt 2>/dev/null
  chmod 600 leaf.key
  chmod 644 leaf.crt
  state=reissued
fi

mkdir -p "$OUT"
cat leaf.crt ca.pem > "$OUT/unity-mcp-chain.crt"
cp leaf.key "$OUT/unity-mcp-leaf.key"

echo "CA=$PKI_DIR/ca.pem"
echo "LEAF=$state"
