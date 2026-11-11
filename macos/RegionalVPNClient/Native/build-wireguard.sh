#!/usr/bin/env bash
set -Eeuo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
checkout="${BUILD_DIR%/Build/*}/SourcePackages/checkouts/wireguard-apple"
test -d "$checkout/Sources/WireGuardKitGo" || {
  echo "Resolve WireGuardApple using the default Xcode DerivedData package location." >&2
  exit 1
}
command -v go >/dev/null || { echo 'Install a Go toolchain for the WireGuard bridge build.' >&2; exit 1; }
make -C "$checkout/Sources/WireGuardKitGo" build \
  PLATFORM_NAME=macosx SDKROOT="$SDKROOT" ARCHS="$ARCHS" \
  CONFIGURATION_BUILD_DIR="$BUILT_PRODUCTS_DIR" CONFIGURATION_TEMP_DIR="$TARGET_TEMP_DIR"
