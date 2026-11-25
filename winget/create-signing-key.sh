#!/usr/bin/env bash
set -euo pipefail
umask 077
out=${1:?usage: create-signing-key.sh NEW_PRIVATE_DIRECTORY}
mkdir -m 700 -- "$out"
cd -- "$out"
tmp=$(mktemp -d ./pem.XXXXXXXX)
trap 'rm -rf -- "$tmp"' EXIT
openssl rand -hex 32 > pfx-password
openssl req -new -x509 -newkey rsa:3072 -sha256 -days 1825 \
    -subj '/CN=Hexor WinGet' -keyout "$tmp/key.pem" -out "$tmp/cert.pem" \
    -passout file:pfx-password -config /dev/stdin <<'CONFIG'
[req]
distinguished_name = dn
x509_extensions = signing
[dn]
[signing]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = codeSigning
CONFIG
openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" \
    -passin fd:3 -passout file:pfx-password 3<pfx-password -out hexor-winget.pfx \
    -keypbe AES-256-CBC -certpbe AES-256-CBC -macalg sha256
openssl x509 -in "$tmp/cert.pem" -outform DER -out hexor-winget.cer
openssl dgst -sha256 hexor-winget.cer
