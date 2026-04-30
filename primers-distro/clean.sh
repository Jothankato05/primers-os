#!/bin/bash
set -e
echo "[PRIMERS] Cleaning build artefacts..."
sudo lb clean
rm -rf config/includes.chroot/primers-brain
rm -rf config/includes.chroot/primers-installer
rm -f primers-os-*.iso build.log
echo "Clean complete."
