#!/bin/bash
# Internal entry point: never run this on the host.
set -euo pipefail
test -f /.dockerenv && test "${YANJARO_DISPOSABLE_CONTAINER:-}" = 1
test "$(id -u)" = 0
unset PYTHONPATH PYTHONHOME QML_IMPORT_PATH QML2_IMPORT_PATH QT_PLUGIN_PATH VIRTUAL_ENV
export PATH=/usr/bin:/bin
target=$1
. /etc/os-release
test "$ID" = "$target"
test "$(uname -m)" = x86_64
printf '%s  %s\n' 7ba013afe09722b774ba180597e6c31dc68fc19516bcb714cea39f18d0812ea3 /input/previous.pkg.tar.zst | sha256sum -c -
if [ "$target" = manjaro ]; then
  test "$(pacman-mirrors --get-branch)" = stable
fi
cat /etc/os-release > /output/distribution.txt
pacman-conf > /output/pacman.conf.txt
pacman -Syu --noconfirm --needed base-devel python desktop-file-utils dbus
mapfile -t dependencies < <(awk '$1 == "depends" || $1 == "checkdepends" || $1 == "makedepends" {print $3}' /input/.SRCINFO | sort -u)
pacman -S --noconfirm --needed "${dependencies[@]}"
pacman -Q > /output/packages.txt
useradd --create-home builder
mkdir /work
cp /input/PKGBUILD /input/.SRCINFO /input/yanjaro-0.2.0rc2.tar.gz /work/
if [ -f /input/yandex_music-3.2.0-py3-none-any.whl ]; then cp /input/yandex_music-3.2.0-py3-none-any.whl /work/; fi
chown -R builder:builder /work
cd /work
runuser -u builder -- makepkg --force --cleanbuild --noconfirm
package=$(runuser -u builder -- makepkg --packagelist)
test -f "$package"
cp "$package" /output/
sha256sum "$package" /input/yanjaro-0.2.0rc2.tar.gz > /output/SHA256SUMS
bsdtar -xOf "$package" .BUILDINFO > /output/BUILDINFO
runuser -u builder -- makepkg --printsrcinfo > /output/SRCINFO
cmp /output/SRCINFO /input/.SRCINFO
printf 'build: PASS\n' > /output/result.txt
# Remove extracted application sources before every installed-entry-point check.
rm -rf /work/src /work/pkg
mkdir -p /home/builder/.config/yanjaro /home/builder/runtime
printf 'synthetic preference\n' > /home/builder/.config/yanjaro/release-test-sentinel
chown -R builder:builder /home/builder
chmod 700 /home/builder/runtime
smoke() {
  cd /tmp
  runuser -u builder -- env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV \
    -u QML_IMPORT_PATH -u QML2_IMPORT_PATH -u QT_PLUGIN_PATH \
    QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/home/builder/runtime \
    XDG_CONFIG_HOME=/home/builder/.config XDG_STATE_HOME=/home/builder/.local/state \
    XDG_CACHE_HOME=/home/builder/.cache \
    dbus-run-session -- /usr/bin/python /input/smoke-installed.py
}
pacman -U --noconfirm /input/previous.pkg.tar.zst
smoke
printf 'rc2-2 install/launch: PASS\n' >> /output/result.txt
pacman -U --noconfirm "$package"
smoke
printf 'candidate install/update/launch: PASS\n' >> /output/result.txt
test "$(cat /home/builder/.config/yanjaro/release-test-sentinel)" = 'synthetic preference'
desktop-file-validate /usr/share/applications/yanjaro.desktop
pacman -Q yanjaro python pyside6 mpv python-mpv python-secretstorage python-jeepney > /output/runtime-versions.txt
pacman -R --noconfirm yanjaro
test ! -e /usr/bin/yanjaro
test ! -e /usr/lib/yanjaro
test ! -e /usr/share/applications/yanjaro.desktop
test -f /home/builder/.config/yanjaro/release-test-sentinel
printf 'remove and synthetic user data preservation: PASS\n' >> /output/result.txt
cat /output/result.txt
