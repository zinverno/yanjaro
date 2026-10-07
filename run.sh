#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -d "$PWD/.runtime/usr/lib" ]; then
    export LD_LIBRARY_PATH="$PWD/.runtime/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec .venv/bin/python -m yanjaro "$@"
