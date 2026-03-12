#!/bin/bash
# Copy gateway_core from monorepo root into this directory for Docker build.
# Run before: docker compose build

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MONO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -d "$MONO_ROOT/gateway_core" ]; then
    echo "ERROR: gateway_core/ not found at $MONO_ROOT/gateway_core"
    exit 1
fi

echo "Copying gateway_core/ → $SCRIPT_DIR/gateway_core/"
rm -rf "$SCRIPT_DIR/gateway_core"
cp -r "$MONO_ROOT/gateway_core" "$SCRIPT_DIR/gateway_core"

# Remove __pycache__
find "$SCRIPT_DIR/gateway_core" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

echo "Done. Ready for: docker compose build"
