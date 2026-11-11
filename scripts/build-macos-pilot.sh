#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
server=${1:-101.34.21.167}
[[ "$server" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 2
pilot="$root/.runtime/poc"
cert="$pilot/control-$server.crt"
test -s "$cert" || { echo "Missing trusted server certificate: $cert" >&2; exit 1; }
source_dir="$root/macos/RegionalVPNClient/PilotApp"
app="$root/macos/RegionalVPNClient/.build/Regional VPN.app"
install -d "$app/Contents/MacOS" "$app/Contents/Resources/vpn_client"
xcrun clang -fobjc-arc -framework Cocoa -mmacosx-version-min=14.0 \
  "$source_dir/main.m" -o "$app/Contents/MacOS/RegionalVPN"
install -m 0644 "$source_dir/Info.plist" "$app/Contents/Info.plist"
install -m 0644 "$cert" "$app/Contents/Resources/control.crt"
install -m 0644 "$root/service/vpn_client/"*.py "$app/Contents/Resources/vpn_client/"
plist="$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :RegionalVPNControlURL https://$server" "$plist"
/usr/libexec/PlistBuddy -c "Set :RegionalVPNPilotDirectory $pilot" "$plist"
/usr/libexec/PlistBuddy -c "Set :RegionalVPNPython $(command -v python3)" "$plist"
codesign --force --sign - "$app"
printf '%s\n' "$app"
