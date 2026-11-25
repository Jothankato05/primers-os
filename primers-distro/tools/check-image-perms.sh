#!/bin/bash
# Build gate: the image's files must belong to root or system accounts, and
# nothing may be writable by everyone (except sticky directories like /tmp).
#
#   check-image-perms.sh ROOT
#
# Regular accounts start at uid 1000 on the installed PC. A file the image
# ships owned by such a uid (for example the uid of the CI runner that
# checked out the source) would belong to whichever account gets that uid
# later, such as the Lab Mode account: owning /etc or /usr/bin is root.
set -euo pipefail
root=${1:?usage: check-image-perms.sh ROOT}
[ -d "$root" ] || { echo "check-image-perms: $root is not a directory" >&2; exit 2; }
status=0

report() {   # $1: what is wrong; stdin: offending paths
  local found
  found=$(head -n 20)
  if [ -n "$found" ]; then
    echo "check-image-perms: $1:" >&2
    printf '%s\n' "$found" | sed "s|^$root|  |" >&2
    status=1
  fi
}

# Owned by a regular account's uid or gid (65534 is nobody/nogroup)
report "owned by a regular account's uid/gid, not root or a system account" < <(
  find "$root" -xdev \( \( -uid +999 ! -uid 65534 \) -o \( -gid +999 ! -gid 65534 \) \) -printf '%p (%U:%G)\n')

# Writable by everyone, other than sticky directories (/tmp, /var/tmp) and
# device nodes (/dev/null and the like; /dev is not packed into the image)
report "writable by every user" < <(
  find "$root" -xdev ! -type l ! -type c ! -type b -perm -0002 ! \( -type d -perm -1000 \) -printf '%p (%m)\n')

# The system directories themselves: root's, writable only by root
system_dirs() {
  local d p uid gid mode
  for d in / /etc /usr /usr/bin /usr/sbin /usr/lib /usr/share /usr/local /var /boot /etc/sudoers.d \
           /etc/polkit-1 /etc/systemd/system /etc/skel /usr/lib/primers /usr/share/primers; do
    p="${root%/}$d"
    [ -d "$p" ] || continue
    read -r uid gid mode < <(stat -c '%u %g %a' "$p")
    if [ "$uid" != 0 ] || [ "$gid" != 0 ] || [ $((8#$mode & 8#022)) -ne 0 ]; then
      echo "$p (${uid}:${gid} $mode)"
    fi
  done
}
report "system directory not root:root or writable by others than root" < <(system_dirs)

if [ "$status" -eq 0 ]; then
  echo "check-image-perms: $root: owners and permissions OK"
fi
exit "$status"
