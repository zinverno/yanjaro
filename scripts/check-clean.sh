#!/bin/bash
# Clean distribution test; only disposable Docker containers are modified.
set -euo pipefail
target=${1:?Usage: check-clean.sh arch|manjaro}
case "$target" in
  arch) image=archlinux:base ;;
  manjaro) image=manjarolinux/base:latest ;;
  *) exit 2 ;;
esac
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker info >/dev/null
input=$(mktemp -d)
name="yanjaro-clean-$target-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$input"' EXIT
cp "$project/packaging/PKGBUILD" "$project/packaging/.SRCINFO" "$input/"
cp "$project/dist/native/yanjaro-0.2.0rc2.tar.gz" "$input/"
cp "$project/dist/native/yanjaro-0.2.0rc2-2-any.pkg.tar.zst" "$input/previous.pkg.tar.zst"
cp "$project/scripts/clean-container.sh" "$project/scripts/smoke-installed.py" "$input/"
# Optional verified wheel cache; makepkg still checks its declared checksum.
sdk="$project/dist/native/yandex_music-3.2.0-py3-none-any.whl"
if [ -f "$sdk" ]; then cp "$sdk" "$input/"; fi
chmod -R a+rX "$input"
output="$project/dist/clean/$target/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$output"
docker pull "$image"
digest=$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')
printf '%s\n' "$digest" > "$output/image.txt"
printf '%s\n' "Results: $output"
timeout --signal=TERM 20m docker run --rm --init --name "$name" \
  --cpus=2 --memory=3g --pids-limit=512 \
  --mount "type=bind,src=$input,dst=/input,readonly" \
  --mount "type=bind,src=$output,dst=/output" \
  --env YANJARO_DISPOSABLE_CONTAINER=1 "$digest" \
  /bin/bash /input/clean-container.sh "$target" 2>&1 | tee "$output/run.log"
