#!/bin/sh
# Uses makepkg; never installs system packages or publishes anything.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$project_dir/scripts/prepare-native.py"
cd "$project_dir/dist/native"
makepkg --force --cleanbuild "$@"
sha256sum ./*.pkg.tar.zst > SHA256SUMS
