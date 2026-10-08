#!/bin/bash
# Standard Docker host only; all pacman/makepkg operations stay in a disposable container.
set -euo pipefail
target=${1:?Usage: check-clean.sh arch|manjaro}
case "$target" in
  arch) image=archlinux:base ;;
  manjaro) image=manjarolinux/base:latest ;;
  *) exit 2 ;;
esac
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output="$project/dist/clean/$target"
mkdir -p "$output"
phase=inputs
failure=FAIL
finish() {
  code=$?
  if [ "$code" -ne 0 ]; then printf '%s: %s (exit %s)\n' "$phase" "$failure" "$code" >> "$output/host-result.txt"; fi
  if [ -n "${name:-}" ]; then docker rm -f "$name" >/dev/null 2>&1 || true; fi
  if [ -n "${scratch:-}" ]; then rm -rf "$scratch"; fi
}
trap finish EXIT
printf 'desktop/audio/account: NOT RUN\n' > "$output/host-result.txt"
git -C "$project" rev-parse HEAD > "$output/harness-commit.txt"
scratch=$(mktemp -d)
input="$scratch/input"
python3 "$project/scripts/prepare-clean.py" "$input"
cp "$input/clean-inputs.json" "$input/candidate-rc2-3.json" "$output/"
cp "$input/SHA256SUMS" "$output/input-SHA256SUMS"
printf 'pinned Git inputs: PASS\n' >> "$output/host-result.txt"
phase=container-availability
failure=BLOCKED
docker info >/dev/null
docker pull --platform linux/amd64 "$image" 2>&1 | tee "$output/pull.log"
digest=$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')
printf '%s\n' "$digest" > "$output/image.txt"
docker image inspect "$image" --format '{{.Id}} {{.Os}}/{{.Architecture}}' > "$output/image-id.txt"
chmod -R a+rX "$input"
name="yanjaro-clean-$target-$$"
phase=container-checks
failure=FAIL
# No host home, source checkout, Docker socket, audio device or credentials are mounted.
timeout --signal=TERM 25m docker run --rm --init --name "$name" \
  --platform linux/amd64 --cpus=2 --memory=4g --pids-limit=512 \
  --mount "type=bind,src=$input,dst=/input,readonly" \
  --mount "type=bind,src=$output,dst=/output" \
  --env YANJARO_DISPOSABLE_CONTAINER=1 "$digest" \
  /bin/bash /input/clean-container.sh "$target" 2>&1 | tee "$output/run.log"
printf 'container checks: PASS\n' >> "$output/host-result.txt"
