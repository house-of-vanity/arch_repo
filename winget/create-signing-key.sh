#!/usr/bin/env bash
set -euo pipefail
umask 077
out=${1:?usage: create-signing-key.sh NEW_PRIVATE_DIRECTORY}
mkdir -m 700 -- "$out"
cd -- "$out"
tmp=$(mktemp -d ./pem.XXXXXXXX)
trap 'rm -rf -- "$tmp"' EXIT
openssl rand -hex 32 > pfx-password
openssl rand -hex 32 > "$tmp/key-password"
cat > "$tmp/openssl.cnf" <<'CONFIG'
[req]
prompt = no
distinguished_name = dn
x509_extensions = signing
[dn]
CN = Hexor WinGet
[signing]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = codeSigning
CONFIG
openssl req -new -x509 -newkey rsa:3072 -sha256 -days 1825 \
    -keyout "$tmp/key.pem" -out "$tmp/cert.pem" \
    -passout "file:$tmp/key-password" -config "$tmp/openssl.cnf"
openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" \
    -passin "file:$tmp/key-password" -passout file:pfx-password -out hexor-winget.pfx \
    -keypbe AES-256-CBC -certpbe AES-256-CBC -macalg sha256
openssl x509 -in "$tmp/cert.pem" -outform DER -out hexor-winget.cer
openssl dgst -sha256 hexor-winget.cer
