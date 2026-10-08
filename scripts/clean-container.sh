#!/bin/bash
# Internal entry point: never run this on the host.
set -euo pipefail
test -f /.dockerenv && test "${YANJARO_DISPOSABLE_CONTAINER:-}" = 1
test "$(id -u)" = 0
unset PYTHONPATH PYTHONHOME QML_IMPORT_PATH QML2_IMPORT_PATH QT_PLUGIN_PATH VIRTUAL_ENV
export PATH=/usr/bin:/bin
export LANG=C.UTF-8
target=$1
phases=(distribution dependencies test-environment source-provenance previous-build candidate-build package-content previous-launch upgrade-launch fresh-launch removal)
declare -A results
for item in "${phases[@]}"; do results[$item]='NOT RUN'; done
phase=distribution
failure=FAIL
report() {
  code=$?
  if [ "$code" -ne 0 ]; then results[$phase]="$failure"; fi
  for item in "${phases[@]}"; do printf '%s: %s\n' "$item" "${results[$item]}"; done > /output/result.txt
  printf 'desktop/audio/account: NOT RUN\n' >> /output/result.txt
  cat /output/result.txt
}
trap report EXIT
cd /input
sha256sum -c SHA256SUMS
. /etc/os-release
test "$ID" = "$target"
test "$(uname -m)" = x86_64
if [ "$target" = manjaro ]; then
  test "$(pacman-mirrors --get-branch)" = stable
  pacman-mirrors --get-branch > /output/branch.txt
fi
cat /etc/os-release > /output/distribution.txt
pacman-conf > /output/pacman.conf.txt
cp /etc/pacman.d/mirrorlist /output/mirrorlist.txt
results[$phase]=PASS
phase=dependencies
failure=BLOCKED
pacman -Syu --noconfirm --needed base-devel python desktop-file-utils dbus
mapfile -t dependencies < <(awk '$1 == "depends" || $1 == "checkdepends" || $1 == "makedepends" {print $3}' /input/.SRCINFO | sort -u)
mapfile -t names < <(printf '%s\n' "${dependencies[@]}" | sed 's/[<>=].*//' | sort -u)
pacman -S --noconfirm --needed "${names[@]}"
failure=FAIL
pacman -T "${dependencies[@]}"
pacman -Q > /output/packages.txt
pacman -Si "${names[@]}" > /output/dependency-repositories.txt
sha256sum /var/lib/pacman/sync/*.db > /output/repository-SHA256SUMS
results[$phase]=PASS
phase=test-environment
# A headless base image has no desktop fonts. Qt still needs real glyph metrics
# for the unmodified click/keyboard tests (including their Cyrillic labels).
pacman -S --noconfirm --needed ttf-dejavu
fc-match sans-serif > /output/test-font.txt
if ! id builder >/dev/null 2>&1; then useradd --create-home builder; fi
test "$(id -u builder)" -ne 0
test "$(getent passwd builder | cut -d: -f6)" = /home/builder
mkdir -p /work /home/builder/runtime
chmod 700 /home/builder/runtime
chown -R builder:builder /work /home/builder
pacman -Q > /output/packages.txt
results[$phase]=PASS
phase=source-provenance
for name in previous candidate; do
  mkdir "/work/$name"
  bsdtar -xf "/input/$name.git.tar" -C "/work/$name"
  chown -R builder:builder "/work/$name"
  epoch=$(python -c 'import json,sys; print(json.load(open("/input/clean-inputs.json"))[sys.argv[1]]["source_date_epoch"])' "$name")
  runuser -u builder -- env SOURCE_DATE_EPOCH="$epoch" python "/work/$name/scripts/prepare-native.py"
  expected=$(python -c 'import json,sys; print(json.load(open("/input/clean-inputs.json"))[sys.argv[1]]["source_sha256"])' "$name")
  printf '%s  %s\n' "$expected" "/work/$name/dist/native/yanjaro-0.2.0rc2.tar.gz" | sha256sum -c -
  mkdir "/output/$name"
  cp "/work/$name/dist/native/"{PKGBUILD,.SRCINFO,yanjaro-0.2.0rc2.tar.gz} "/output/$name/"
done
cmp /work/candidate/dist/native/PKGBUILD /input/PKGBUILD
cmp /work/candidate/dist/native/.SRCINFO /input/.SRCINFO
results[$phase]=PASS
for name in previous candidate; do
  phase="$name-build"
  cd "/work/$name/dist/native"
  # No --nocheck, --nodeps, --skipchecksums or substituted dependency environment.
  runuser -u builder -- makepkg --force --cleanbuild --noconfirm 2>&1 | tee "/output/$name/makepkg.log"
  package=$(runuser -u builder -- makepkg --packagelist)
  test -f "$package"
  cp "$package" "/output/$name/"
  bsdtar -xOf "$package" .BUILDINFO > "/output/$name/BUILDINFO"
  bsdtar -xOf "$package" .PKGINFO > "/output/$name/PKGINFO"
  bsdtar -tf "$package" > "/output/$name/files.txt"
  runuser -u builder -- makepkg --printsrcinfo > "/output/$name/generated.SRCINFO"
  cmp "/output/$name/generated.SRCINFO" "/output/$name/.SRCINFO"
  results[$phase]=PASS
done
phase=package-content
for name in previous candidate; do
  version=$(python -c 'import json,sys; print(json.load(open("/input/clean-inputs.json"))[sys.argv[1]]["version"])' "$name")
  package="/output/$name/yanjaro-$version-any.pkg.tar.zst"
  python /input/check-package.py "$package" --source "/work/$name/yanjaro" --version "$version" | tee "/output/$name/package-check.txt"
  (cd "/output/$name" && sha256sum ./*.pkg.tar.zst ./*.tar.gz PKGBUILD .SRCINFO > SHA256SUMS)
done
results[$phase]=PASS
# No extracted application tree remains when the installed launcher runs.
cd /tmp
rm -rf /work/candidate /work/previous
mkdir -p /home/builder/.config/yanjaro
printf 'synthetic preference\n' > /home/builder/.config/yanjaro/release-test-sentinel
chown -R builder:builder /home/builder
smoke() {
  cd /tmp
  runuser -u builder -- env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \
    -u QML_IMPORT_PATH -u QML2_IMPORT_PATH -u QT_PLUGIN_PATH \
    QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/home/builder/runtime \
    XDG_CONFIG_HOME=/home/builder/.config XDG_STATE_HOME=/home/builder/.local/state \
    XDG_CACHE_HOME=/home/builder/.cache \
    dbus-run-session -- /usr/bin/python /input/smoke-installed.py
}
phase=previous-launch
pacman -U --noconfirm /output/previous/yanjaro-0.2.0rc2-2-any.pkg.tar.zst
test "$(pacman -Q yanjaro)" = 'yanjaro 0.2.0rc2-2'
smoke 2>&1 | tee /output/previous/smoke.log
results[$phase]=PASS
phase=upgrade-launch
pacman -U --noconfirm /output/candidate/yanjaro-0.2.0rc2-3-any.pkg.tar.zst
test "$(pacman -Q yanjaro)" = 'yanjaro 0.2.0rc2-3'
smoke 2>&1 | tee /output/candidate/upgrade-smoke.log
test "$(cat /home/builder/.config/yanjaro/release-test-sentinel)" = 'synthetic preference'
desktop-file-validate /usr/share/applications/yanjaro.desktop
pacman -Qkk yanjaro
pacman -Q yanjaro python pyside6 mpv python-mpv python-secretstorage python-jeepney > /output/runtime-versions.txt
results[$phase]=PASS
phase=fresh-launch
pacman -R --noconfirm yanjaro
pacman -U --noconfirm /output/candidate/yanjaro-0.2.0rc2-3-any.pkg.tar.zst
smoke 2>&1 | tee /output/candidate/fresh-smoke.log
results[$phase]=PASS
phase=removal
pacman -R --noconfirm yanjaro
test ! -e /usr/bin/yanjaro
test ! -e /usr/lib/yanjaro
test ! -e /usr/share/applications/yanjaro.desktop
test ! -e /usr/share/icons/hicolor/scalable/apps/yanjaro.svg
test ! -e /usr/share/doc/yanjaro
test ! -e /usr/share/licenses/yanjaro
! pacman -Q yanjaro
test "$(cat /home/builder/.config/yanjaro/release-test-sentinel)" = 'synthetic preference'
results[$phase]=PASS
