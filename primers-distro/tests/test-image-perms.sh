#!/bin/bash
# Tests for the image ownership gate (tools/check-image-perms.sh) and for
# build.sh's install_tree, which copies checkout trees into the image.
# Needs root (it creates files owned by other uids): sudo in CI.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
gate="$here/tools/check-image-perms.sh"
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }
eval "$(sed -n '/^install_tree() {/,/^}/p' "$here/build.sh")"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fails=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }
expect() {   # expect ok|bad NAME ROOT
  local want=$1 name=$2 root=$3 got=ok
  "$gate" "$root" > "$work/out" 2>&1 || got=bad
  if [ "$got" = "$want" ]; then pass "$name"; else fail "$name"; cat "$work/out"; fi
}

# A minimal system tree as the bootstrap leaves it: root's, sticky /tmp
base() {
  local r=$1
  mkdir -p "$r"/{etc/skel,usr/bin,usr/lib,var/tmp,tmp,dev}
  chmod 1777 "$r/tmp" "$r/var/tmp"
  mknod -m 666 "$r/dev/null" c 1 3
  echo x > "$r/usr/bin/tool"; chmod 0755 "$r/usr/bin/tool"
}

# A checkout as a CI runner has it: owned by uid 1001, group-writable file
src="$work/checkout"
mkdir -p "$src/etc/skel/.config" "$src/usr/bin" "$src/usr/lib/primers" "$src/__pycache__"
echo rc > "$src/etc/skel/.config/rc"; chmod 0664 "$src/etc/skel/.config/rc"
echo '#!/bin/sh' > "$src/usr/bin/primers-exam"; chmod 0775 "$src/usr/bin/primers-exam"
echo junk > "$src/__pycache__/x.pyc"
chown -R 1001:1001 "$src"

r="$work/clean"; base "$r"
expect ok "a root-owned tree with sticky /tmp and device nodes passes" "$r"

r="$work/cp-a"; base "$r"; cp -a "$src/." "$r/"
expect bad "cp -a from a uid-1001 checkout is refused (/, /etc, /usr/bin become uid 1001)" "$r"

r="$work/install-tree"; base "$r"; chmod 0711 "$r/usr/lib"
install_tree "$src" "$r" --exclude=__pycache__
expect ok "install_tree from a uid-1001 checkout passes" "$r"
if [ "$(stat -c '%u:%g %a' "$r/usr/bin/primers-exam")" = "0:0 755" ] &&
   [ "$(stat -c '%u:%g %a' "$r/etc/skel/.config/rc")" = "0:0 644" ]; then
  pass "install_tree: files are root's, group/other write dropped"
else
  fail "install_tree: files are root's, group/other write dropped"
fi
if [ "$(stat -c '%a' "$r/usr/lib")" = 711 ] && [ "$(stat -c '%u' "$r")" = 0 ]; then
  pass "install_tree: existing directories keep their owner and mode"
else
  fail "install_tree: existing directories keep their owner and mode"
fi
if [ ! -e "$r/__pycache__" ]; then pass "install_tree: excludes apply"; else fail "install_tree: excludes apply"; fi

r="$work/world"; base "$r"; echo x > "$r/etc/open"; chmod 0666 "$r/etc/open"
expect bad "a world-writable file is refused" "$r"

r="$work/worlddir"; base "$r"; mkdir "$r/var/drop"; chmod 0777 "$r/var/drop"
expect bad "a world-writable directory without the sticky bit is refused" "$r"

r="$work/gid"; base "$r"; chgrp 1000 "$r/usr/bin/tool"
expect bad "a file with a regular account's gid is refused" "$r"

r="$work/groupw"; base "$r"; chmod 0775 "$r/usr/bin"
expect bad "a group-writable system directory is refused" "$r"

r="$work/nobody"; base "$r"; chown 65534:65534 "$r/usr/bin/tool"
expect ok "nobody/nogroup is a system account" "$r"

echo
if [ "$fails" -eq 0 ]; then echo "all image permission tests passed"; else echo "$fails failed"; exit 1; fi
