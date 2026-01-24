#!/usr/bin/env bash
# Custom wrapper for xcode_backend.sh that strips extended attributes
# before the Flutter build to prevent code signing failures

# Strip extended attributes from the Flutter engine cache
# This fixes the "resource fork, Finder information, or similar detritus not allowed" error
xattr -cr "$FLUTTER_ROOT/bin/cache/artifacts/engine" 2>/dev/null || true

# Also strip from the build directory if it exists
if [ -d "${BUILT_PRODUCTS_DIR}" ]; then
    xattr -cr "${BUILT_PRODUCTS_DIR}" 2>/dev/null || true
fi

# Call the original xcode_backend.sh
exec /bin/sh "$FLUTTER_ROOT/packages/flutter_tools/bin/xcode_backend.sh" "$@"
