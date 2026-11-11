#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
native="$root/macos/RegionalVPNClient/Native"
command -v xcodegen >/dev/null || { echo 'Install XcodeGen on the build Mac: brew install xcodegen' >&2; exit 1; }
if [[ $# -gt 1 ]]; then
  echo 'Usage: prepare-macos-native.sh [public-control-certificate.pem]' >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  mkdir -p "$native/LocalResources"
  openssl x509 -in "$1" -outform DER -out "$native/LocalResources/control.cer"
elif [[ -e "$native/LocalResources/control.cer" ]]; then
  echo 'An existing local trust certificate is present. Pass its PEM file explicitly, or move it away to use system trust.' >&2
  exit 2
fi
xcodegen generate --spec "$native/project.yml" --project "$native"
printf '%s\n' "$native/RegionalVPNNative.xcodeproj"
