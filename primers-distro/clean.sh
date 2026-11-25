#!/usr/bin/env bash
# PRIMERS OS — remove build output.
#   sudo ./clean.sh          remove ISO, image tree and stage stamps (keeps the chroot)
#   sudo ./clean.sh --all    remove everything, including the chroot and caches
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=config/build.conf
source config/build.conf
WORK="${PRIMERS_WORK_DIR:-$PWD/work}"

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo $0 $*" >&2; exit 1; }

# Never delete through live mounts
for m in run sys proc dev/pts dev; do
  if mountpoint -q "$WORK/chroot/$m" 2>/dev/null; then
    umount "$WORK/chroot/$m" || umount -l "$WORK/chroot/$m"
  fi
done

echo "[PRIMERS] Cleaning build artefacts..."
rm -f "$ISO_NAME" "$ISO_NAME.sha256" build.log
rm -rf "$WORK/image"
rm -f "$WORK"/.stamp-image "$WORK"/.stamp-finalize "$WORK"/.stamp-customize

if [ "${1:-}" = "--all" ]; then
  echo "[PRIMERS] Removing chroot and caches in $WORK"
  rm -rf "$WORK"
fi
echo "Clean complete."
