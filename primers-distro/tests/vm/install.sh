#!/bin/bash
# Install PRIMERS OS from the live session onto a blank disk, without the
# installer's screens: the same steps Calamares runs with our configuration
# (installer/calamares), for VM tests that need an installed system.
#   install.sh DISK STAFF_PASSWORD        e.g. install.sh /dev/vda staffpass
# Legacy BIOS, one ext4 partition. ERASES DISK. Runs as root in the live VM.
set -euo pipefail
disk=${1:?disk}
password=${2:?staff password}
squashfs=/cdrom/casper/filesystem.squashfs
target=/target

grep -qw boot=casper /proc/cmdline || { echo "install.sh: not a live session" >&2; exit 1; }
[ -b "$disk" ] || { echo "install.sh: $disk is not a disk" >&2; exit 1; }
[ -f "$squashfs" ] || { echo "install.sh: $squashfs missing" >&2; exit 1; }
if [ -n "$(lsblk -nro MOUNTPOINT "$disk" | grep -v '^$' || true)" ]; then
  echo "install.sh: $disk is in use" >&2; exit 1
fi

echo "== partition (msdos, one bootable ext4 partition)"
wipefs -aq "$disk"
printf 'label: dos\ntype=83, bootable\n' | sfdisk -q "$disk"
udevadm settle
part="${disk}1"
mkfs.ext4 -q -F -L PRIMERS "$part"
mkdir -p "$target"
mount "$part" "$target"

echo "== unpackfs ($squashfs)"
unsquashfs -f -q -n -d "$target" "$squashfs" > /dev/null

echo "== machineid, fstab, hostname"
: > "$target/etc/machine-id"
uuid=$(blkid -s UUID -o value "$part")
printf '# /etc/fstab: written by the PRIMERS OS installer\nUUID=%s / ext4 defaults,errors=remount-ro 0 1\n' \
  "$uuid" > "$target/etc/fstab"
echo staff-primers > "$target/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 staff-primers\n::1 localhost ip6-localhost ip6-loopback\n' \
  > "$target/etc/hosts"

for fs in dev dev/pts proc sys run; do
  mount --bind "/$fs" "$target/$fs"
done
in_target() { chroot "$target" "$@"; }

echo "== shellprocess@cleanup, packages, shellprocess@finalize"
in_target rm -f /usr/share/applications/install-primers.desktop /etc/skel/Desktop/install-primers.desktop \
  /etc/casper.conf /etc/sudoers.d/casper
in_target rmdir --ignore-fail-on-non-empty /etc/skel/Desktop 2>/dev/null || true
in_target env DEBIAN_FRONTEND=noninteractive apt-get -y -q remove --purge calamares casper > /dev/null 2>&1 || true
in_target env DEBIAN_FRONTEND=noninteractive apt-get -y -q autoremove --purge > /dev/null 2>&1 || true

echo "== users (staff, administrator)"
in_target useradd --create-home --shell /bin/bash --comment "Lab staff" \
  --groups adm,audio,cdrom,dip,plugdev,users,video,sudo staff
printf 'staff:%s\n' "$password" | in_target chpasswd

echo "== initramfs, grubcfg, bootloader"
in_target update-initramfs -u -k all > /dev/null
in_target grub-install --target=i386-pc "$disk"
in_target update-grub 2> /dev/null

echo "== umount"
sync
for fs in run sys proc dev/pts dev; do
  umount "$target/$fs"
done
umount "$target"
sync
echo "installed on $disk"
