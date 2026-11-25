#!/bin/bash
# Tests for the live installer's sfdisk correction
# (overlays/usr/lib/primers/installer/sfdisk). With a fake sfdisk for every
# case; as root, also against a real GPT disk on a loop device, showing the
# unpatched request fails and the corrected one works.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
shim="$here/overlays/usr/lib/primers/installer/sfdisk"
work=$(mktemp -d)
loop=""
cleanup() { [ -n "$loop" ] && losetup -d "$loop" 2> /dev/null; rm -rf "$work"; }
trap cleanup EXIT
fails=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }
check() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (got '$2', want '$3')"; fi; }

# A fake sfdisk: --dump prints $work/dump; anything else records its
# arguments and input
cat > "$work/sfdisk" <<FAKE
#!/bin/bash
if [ "\$1" = --dump ]; then cat "$work/dump"; exit 0; fi
printf '%s\n' "\$*" > "$work/args"
cat > "$work/input"
echo "Created a new partition 2"
FAKE
chmod +x "$work/sfdisk"
export PRIMERS_REAL_SFDISK="$work/sfdisk"
gpt='label: gpt
device: /dev/vda
unit: sectors
first-lba: 2048
last-lba: 50331614
sector-size: 512'
mkdir "$work/bin"             # logger may be missing in minimal containers
printf '#!/bin/sh\nexit 0\n' > "$work/bin/logger"; chmod +x "$work/bin/logger"
command -v logger > /dev/null || export PATH="$work/bin:$PATH"

echo "$gpt" > "$work/dump"
printf 'start=1052672 size=49278973\nwrite\n' | "$shim" --force --append /dev/vda > /dev/null
check "GPT: a partition past the last usable sector is trimmed to end there" \
  "$(head -n1 "$work/input")" "start=1052672 size=49278943"
check "GPT: the rest of the script is passed on" "$(tail -n1 "$work/input")" "write"
check "GPT: sfdisk gets the same arguments" "$(cat "$work/args")" "--force --append /dev/vda"

printf 'start=1052672 type=0FC63DAF-8483-4772-8E79-3D69D8477DE4 size=1000\nwrite\n' \
  | "$shim" --force --append /dev/vda > /dev/null
check "GPT: a partition that fits is unchanged" "$(head -n1 "$work/input")" \
  "start=1052672 type=0FC63DAF-8483-4772-8E79-3D69D8477DE4 size=1000"

printf 'label: dos\ndevice: /dev/vda\nunit: sectors\n' > "$work/dump"
printf 'start=2048 size=50329600\nwrite\n' | "$shim" --force --append /dev/vda > /dev/null
check "MBR: unchanged (no backup table at the end)" "$(head -n1 "$work/input")" "start=2048 size=50329600"

echo "$gpt" > "$work/dump"
echo "untouched" | "$shim" --part-label /dev/vda 1 EFI > /dev/null
check "other calls: arguments passed on" "$(cat "$work/args")" "--part-label /dev/vda 1 EFI"
check "other calls: input passed on" "$(cat "$work/input")" "untouched"

# A real disk, as root: what Calamares 3.2.61 asks for fails without the
# correction and works with it
sfdisk_bin=$(command -v sfdisk || echo /sbin/sfdisk)
if [ "$(id -u)" = 0 ] && command -v losetup > /dev/null && [ -x "$sfdisk_bin" ]; then
  unset PRIMERS_REAL_SFDISK
  sfdisk() { "$sfdisk_bin" "$@"; }
  truncate -s 64M "$work/disk.img"
  loop=$(losetup --find --show "$work/disk.img")
  printf 'label: gpt\nwrite\n' | sfdisk --quiet "$loop" > /dev/null
  total=$((64 * 1024 * 1024 / 512))
  request="start=2048 size=$((total - 4 - 2048))"      # ends at total-4, as in the failing install
  if printf '%s\nwrite\n' "$request" | sfdisk --force --append "$loop" > /dev/null 2>&1; then
    fail "real GPT disk: the uncorrected request is refused"
  else
    pass "real GPT disk: the uncorrected request is refused"
  fi
  printf '%s\nwrite\n' "$request" | "$shim" --force --append "$loop" > "$work/shim.out" 2>&1 || cat "$work/shim.out"
  end=$(sfdisk --dump "$loop" | sed -n 's/.*start= *\([0-9]*\), size= *\([0-9]*\).*/\1 \2/p' | awk '{print $1 + $2 - 1}')
  last=$(sfdisk --dump "$loop" | sed -n 's/^last-lba: *//p')
  check "real GPT disk: with the correction the partition is created, ending at the last usable sector" \
    "$end" "$last"
else
  echo "SKIP  real GPT disk (needs root and losetup)"
fi

echo
if [ "$fails" -eq 0 ]; then echo "all installer sfdisk tests passed"; else echo "$fails failed"; exit 1; fi
