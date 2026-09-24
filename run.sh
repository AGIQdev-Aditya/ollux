#!/usr/bin/env bash
# ollux launcher script
# Fix for WebKitWebProcess crash on Linux hybrid Intel/NVIDIA Wayland setups
export WEBKIT_DISABLE_DMABUF_RENDERER=1

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
if [ -d "$DIR/.venv" ]; then
    source "$DIR/.venv/bin/activate"
fi
exec python3 "$DIR/src/main.py" "$@"
