#!/bin/bash
# Install PRIMERS OS from the live session onto a blank disk, without the
# installer's screens: the same steps Calamares runs with our configuration
# (installer/calamares), for VM tests that need an installed system.
#   install.sh DISK STAFF_PASSWORD        e.g. install.sh /dev/vda staffpass
# Like the installer, it follows the firmware the live session booted with:
# legacy BIOS gets an msdos disk with one ext4 partition and GRUB in the MBR;
# UEFI gets GPT, a 512 MB EFI system partition and Ubuntu's signed boot
# chain (shim -> signed GRUB), plus the fallback loader, so Secure Boot
# works. ERASES DISK. Runs as root in the live VM.
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

efi=false
[ -d /sys/firmware/efi ] && efi=true
wipefs -aq "$disk"
if $efi; then
  echo "== partition (gpt: EFI system partition, ext4)"
  printf 'label: gpt\nsize=512MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name=EFI\ntype=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name=PRIMERS\n' \
    | sfdisk -q "$disk"
  udevadm settle
  esp="${disk}1" part="${disk}2"
  mkfs.vfat -F 32 -n EFI "$esp" > /dev/null
else
  echo "== partition (msdos, one bootable ext4 partition)"
  printf 'label: dos\ntype=83, bootable\n' | sfdisk -q "$disk"
  udevadm settle
  part="${disk}1"
fi
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
if $efi; then
  mkdir -p "$target/boot/efi"
  mount "$esp" "$target/boot/efi"
  printf 'UUID=%s /boot/efi vfat umask=0077 0 1\n' "$(blkid -s UUID -o value "$esp")" >> "$target/etc/fstab"
fi
echo labadmin-primers > "$target/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 labadmin-primers\n::1 localhost ip6-localhost ip6-loopback\n' \
  > "$target/etc/hosts"

for fs in dev dev/pts proc sys run; do
  mount --bind "/$fs" "$target/$fs"
done
$efi && mount -t efivarfs efivarfs "$target/sys/firmware/efi/efivars" 2> /dev/null || true
in_target() { chroot "$target" "$@"; }

echo "== shellprocess@cleanup, packages, shellprocess@finalize"
in_target rm -f /usr/share/applications/install-primers.desktop /etc/skel/Desktop/install-primers.desktop \
  /etc/casper.conf /etc/sudoers.d/casper
in_target rmdir --ignore-fail-on-non-empty /etc/skel/Desktop 2>/dev/null || true
in_target env DEBIAN_FRONTEND=noninteractive apt-get -y -q remove --purge calamares casper > /dev/null 2>&1 || true
in_target env DEBIAN_FRONTEND=noninteractive apt-get -y -q autoremove --purge > /dev/null 2>&1 || true

echo "== users (the staff administrator account, labadmin)"
in_target useradd --create-home --user-group --shell /bin/bash --comment "Lab staff" \
  --groups adm,audio,cdrom,dip,plugdev,users,video,sudo labadmin
printf 'labadmin:%s\n' "$password" | in_target chpasswd

echo "== initramfs, grubcfg, bootloader"
in_target update-initramfs -u -k all > /dev/null
if $efi; then
  # bootloader.conf: efiBootloaderId ubuntu, installEFIFallback true
  in_target grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu \
    --uefi-secure-boot --recheck
  in_target mkdir -p /boot/efi/EFI/BOOT
  in_target cp /boot/efi/EFI/ubuntu/shimx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI
  in_target cp /boot/efi/EFI/ubuntu/grubx64.efi /boot/efi/EFI/ubuntu/mmx64.efi /boot/efi/EFI/BOOT/
else
  in_target grub-install --target=i386-pc "$disk"
fi
in_target update-grub 2> /dev/null

echo "== umount"
sync
$efi && { umount "$target/sys/firmware/efi/efivars" 2> /dev/null || true; umount "$target/boot/efi"; }
for fs in run sys proc dev/pts dev; do
  umount "$target/$fs"
done
umount "$target"
sync
echo "installed on $disk"
