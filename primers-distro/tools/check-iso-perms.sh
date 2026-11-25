#!/bin/bash
# Release gate: the same owner and permission rules as check-image-perms.sh,
# applied to a finished ISO's root filesystem (casper/filesystem.squashfs),
# read straight out of the ISO without unpacking it. Run on every ISO before
# it is published, including ISOs an earlier workflow run built.
#
#   check-iso-perms.sh ISO
set -euo pipefail
iso=${1:?usage: check-iso-perms.sh ISO}
lba=$(xorriso -indev "$iso" -find /casper/filesystem.squashfs -exec report_lba -- 2>/dev/null \
      | awk -F',' '/filesystem\.squashfs/ { gsub(/ /, "", $2); print $2 }')
[ -n "$lba" ] || { echo "check-iso-perms: no casper/filesystem.squashfs in $iso" >&2; exit 2; }

listing=$(mktemp)
trap 'rm -f "$listing"' EXIT
unsquashfs -o $((lba * 2048)) -lln "$iso" > "$listing"
entries=$(grep -c '^[-dlcbps]' "$listing" || true)
[ "$entries" -gt 1000 ] || { echo "check-iso-perms: could not list the root filesystem" >&2; exit 2; }

# unsquashfs -lln: "drwxr-xr-x 0/0 296 2026-11-24 23:05 squashfs-root/etc"
awk '
  function bad(why) { if (n[why]++ < 20) print why ": " path " (" $1 " " $2 ")" > "/dev/stderr"; failed = 1 }
  /^[-dlcbps]/ {
    path = $0; sub(/^[^ ]+ +[^ ]+ +[^ ]+ +[^ ]+ +[^ ]+ +/, "", path); sub(/ -> .*/, "", path)
    sub(/^squashfs-root/, "", path); if (path == "") path = "/"
    split($2, id, "/"); type = substr($1, 1, 1)
    if ((id[1] >= 1000 && id[1] != 65534) || (id[2] >= 1000 && id[2] != 65534))
      bad("owned by a regular account")
    if (type != "l" && type != "c" && type != "b" && substr($1, 9, 1) == "w" &&
        !(type == "d" && substr($1, 10, 1) ~ /[tT]/))
      bad("writable by every user")
    if (path ~ /^\/(etc|usr|usr\/bin|usr\/sbin|usr\/lib|usr\/share|var|boot|etc\/sudoers\.d|etc\/polkit-1|etc\/systemd\/system|etc\/skel|usr\/lib\/primers|usr\/share\/primers)?$/ &&
        type == "d" && ($2 != "0/0" || substr($1, 6, 1) == "w" || substr($1, 9, 1) == "w"))
      bad("system directory not root:root or writable by others than root")
  }
  END { exit failed }
' "$listing" || { echo "check-iso-perms: $iso: refusing it" >&2; exit 1; }
echo "check-iso-perms: $iso: $entries entries, owners and permissions OK"
