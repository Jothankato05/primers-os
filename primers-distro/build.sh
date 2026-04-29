#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "╔══════════════════════════════════════════╗"
echo "║   PRIMERS OS — ISO Build System v1.0     ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Dependency check
for dep in lb mksquashfs xorriso mtools; do
  if ! command -v $dep &>/dev/null; then
    echo "[ERROR] Missing: $dep"
    echo "Run:"
    echo "  sudo apt install -y live-build squashfs-tools xorriso"
    echo "  sudo apt install -y grub-pc-bin grub-efi-amd64-bin mtools"
    exit 1
  fi
done

# Copy brain into chroot overlay
echo "[BUILD] Copying PRIMERS brain..."
mkdir -p config/includes.chroot/primers-brain
cp -r ../primers-os/. config/includes.chroot/primers-brain/

# Copy launcher scripts from overlays
echo "[BUILD] Copying filesystem overlays..."
cp -r overlays/. config/includes.chroot/

# Copy calamares config
mkdir -p config/includes.chroot/primers-installer
cp -r installer/calamares/. config/includes.chroot/primers-installer/

# Copy module registry
mkdir -p config/includes.chroot/usr/lib/primers/modules
cp overlays/usr/lib/primers/modules/module_registry.json \
   config/includes.chroot/usr/lib/primers/modules/

# Mark all hooks executable
chmod +x config/hooks/chroot/*.hook.chroot
chmod +x auto/config auto/build auto/clean

# Mark launcher scripts executable
chmod +x config/includes.chroot/usr/bin/primers
chmod +x config/includes.chroot/usr/bin/primers-install
chmod +x config/includes.chroot/usr/bin/primers-compat

# Init live-build config
echo "[BUILD] Initialising live-build..."
bash auto/config

# Build
echo "[BUILD] Building ISO — this takes 30-90 minutes..."
echo "[BUILD] Log: build.log"
sudo lb build 2>&1 | tee build.log

# Rename and report
ISO="primers-os-1.0-genesis-amd64.iso"
if ls live-image-amd64.hybrid.iso 2>/dev/null; then
  mv live-image-amd64.hybrid.iso "$ISO"
  SIZE=$(du -sh "$ISO" | cut -f1)
  echo ""
  echo "╔══════════════════════════════════════════╗"
  echo "║   BUILD COMPLETE                         ║"
  echo "╚══════════════════════════════════════════╝"
  echo "  Output: $ISO"
  echo "  Size:   $SIZE"
  echo ""
  echo "  Test with QEMU (2GB RAM / minimum spec):"
  echo "  qemu-system-x86_64 -cdrom $ISO -m 2048 -enable-kvm -vga std -net nic -net user"
  echo ""
  echo "  Test with QEMU (4GB RAM / gaming spec):"
  echo "  qemu-system-x86_64 -cdrom $ISO -m 4096 -enable-kvm -cpu host -smp 4 -vga virtio -net nic -net user"
else
  echo "[ERROR] Build failed. Check build.log"
  exit 1
fi
