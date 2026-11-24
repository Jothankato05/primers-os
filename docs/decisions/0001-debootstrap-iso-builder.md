# 0001 — Build the ISO with debootstrap + GRUB instead of live-build

- **Status:** accepted
- **Date:** 2026-11-24

## Context

The ISO was built with `live-build`. Every CI build (runs 7–13, tags
`v1.0.2`–`v1.0.8-genesis`) failed. On the `ubuntu-22.04` runner, `apt install
live-build` gives version **3.0~a57-1ubuntu41** — the 2012-era branch Ubuntu
still carries — not the modern Debian live-build. In that version:

- `--mode ubuntu` with the syslinux bootloader always requires
  `gfxboot-theme-ubuntu`, and every theme option requires a
  `syslinux-themes-<name>` package. None of these exist in jammy.
- Chroot firmware detection downloads per-component `Contents-*.gz` files
  that Ubuntu mirrors don't publish (Debian layout).
- `--linux-packages linux-image-generic --linux-flavours generic` produces
  the package name `linux-image-generic-generic`.

Separately, the package lists used Debian names (`firmware-linux-free`) and
`firefox`, which on jammy is a snap transition package that can't be
installed in a chroot.

## Decision

Replace live-build with a small, staged `build.sh` that runs `debootstrap`,
installs packages in a chroot with apt, applies overlays and hooks, builds
a casper squashfs and assembles a hybrid BIOS/UEFI ISO with `xorriso`, using
Ubuntu's signed shim and GRUB for UEFI so Secure Boot works. The
existing package lists, hooks and overlays are kept. Firefox comes from
Mozilla's signed APT repository (fingerprint-pinned in `build.sh`).

## Consequences

- The build depends only on tools available on any Ubuntu/Debian host and
  was verified end to end in QEMU: the ISO boots to the desktop on BIOS and
  UEFI, Calamares installs to a blank disk (UEFI, GPT, ext4), and the
  installed system boots from its own GRUB to the login screen and desktop.
- `tools/check-packages.py` validates every package name against the jammy
  archive in CI, so naming errors fail in seconds.
- The live ISO boots with Secure Boot enabled (shim → signed GRUB → signed
  kernel, as on Ubuntu media); the first version used `grub-mkrescue`, whose
  unsigned GRUB needed Secure Boot turned off.
- We maintain ~400 lines of shell instead of a live-build configuration.
