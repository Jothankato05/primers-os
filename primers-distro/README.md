# ⚛ PRIMERS OS — Distribution & ISO build

Builds the PRIMERS OS live/installable ISO from Ubuntu 22.04 ("jammy")
packages: `debootstrap` a base system, install packages in a chroot, apply
PRIMERS configuration, compress it to squashfs and wrap it in a hybrid GRUB
ISO that boots on **BIOS and UEFI** and writes straight to a USB stick.

## Requirements

- An Ubuntu 22.04 or 24.04 (or Debian 12) machine/VM/WSL2 with root access
- ~20 GB free disk space and an internet connection
- Build tools:

```bash
sudo apt-get install -y debootstrap squashfs-tools xorriso mtools grub-pc-bin grub-efi-amd64-bin grub-common gnupg curl
```

## Build

```bash
cd primers-distro
sudo ./build.sh
```

Output: `primers-os-1.0-genesis-amd64.iso` plus `.sha256`. A full build takes
roughly 10–30 minutes, mostly downloading packages and compressing.

### Stages

The build runs in five stages and remembers which ones finished, so an
interrupted build resumes where it stopped:

| Stage | What it does |
|---|---|
| `bootstrap` | `debootstrap` a minimal Ubuntu jammy |
| `packages` | apt sources (+ Mozilla's repo for Firefox), HWE kernel, casper, every `config/packages-lists/*.list.chroot` |
| `customize` | copy `overlays/`, the PRIMERS Brain and the installer config; run `config/hooks/chroot/*.hook.chroot` |
| `finalize` | rebuild the initramfs, clean caches, reset machine-id/SSH keys, security checks |
| `image` | squashfs + GRUB menu + hybrid ISO |

```bash
sudo ./build.sh --from customize   # changed a hook/overlay/the brain: redo from here
sudo ./build.sh --only image       # just re-pack the ISO
sudo ./build.sh --list             # list stages
sudo ./clean.sh                    # remove the ISO and image (keeps the chroot)
sudo ./clean.sh --all              # remove everything
```

### Options (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PRIMERS_WORK_DIR` | `./work` | where the chroot and image live (needs ~15 GB) |
| `MIRROR` | `http://archive.ubuntu.com/ubuntu` | use a closer Ubuntu mirror |
| `SQUASHFS_COMP` | `xz` | `zstd` builds/boots faster, `xz` is smaller |
| `KERNEL_PACKAGE` | `linux-generic-hwe-22.04` | kernel metapackage |
| `BUILD_CA_FILE` | – | extra CA trusted **only during the build** (TLS-inspecting proxies); removed before packing, and the build fails if it is still present |

All defaults live in [`config/build.conf`](config/build.conf). Pass variables
through sudo: `sudo MIRROR=http://mirror.example/ubuntu ./build.sh`.

## Test in a VM

```bash
# BIOS
qemu-system-x86_64 -enable-kvm -m 4096 -smp 2 -cdrom primers-os-1.0-genesis-amd64.iso

# UEFI, with a disk to install onto
qemu-img create -f qcow2 disk.qcow2 30G
qemu-system-x86_64 -enable-kvm -m 4096 -smp 2 -bios /usr/share/ovmf/OVMF.fd \
  -cdrom primers-os-1.0-genesis-amd64.iso -drive file=disk.qcow2,if=virtio
```

The live session logs in automatically as `primers` (no password) and opens
the PRIMERS Brain. **Install PRIMERS OS** is on the desktop.

## How the pieces fit

```
config/
  build.conf                    versions, mirrors, kernel, ISO name
  packages-lists/
    base.list.chroot            core system, desktop, installer, fonts, brain runtime
    primers.list.chroot         Wine, gaming stack, media
    exclude.list                packages that must never be installed
  hooks/chroot/                 run in order inside the chroot
    0010-setup-system           hostname, locale, firewall, NetworkManager
    0020-install-brain          compile + smoke-test the PRIMERS Brain
    0030-configure-wine         open .exe/.msi with primers-compat
    0040-configure-gaming       sysctl, zram, Lutris defaults, file limits
    0050-configure-desktop      artwork, Plymouth splash, GRUB theme fonts, LightDM, GTK
    0060-performance-kernel     /etc/default/grub, CPU governor service
    0070-configure-installer    "Install PRIMERS OS" launcher
overlays/                       copied verbatim into the OS root
  usr/bin/primers               launches the brain
  usr/bin/primers-terminal      brain in a terminal window (falls back to a shell)
  usr/bin/primers-install       module installer
  usr/bin/primers-compat        Windows program launcher (Wine)
  usr/lib/primers/modules/      module registry (JSON)
  etc/skel/                     defaults for every new user (Openbox, tint2, PCManFM…)
installer/calamares/            installer: settings.conf, modules/*.conf, branding/
tools/check-packages.py         verifies every package name against the Ubuntu archive
```

### Live session vs installed system

- The live user is created at boot by **casper** from `/etc/casper.conf`; it
  never exists in the image, so installed machines don't inherit a known
  password or passwordless sudo.
- The installer copies the squashfs to disk, removes live-only bits
  (casper, Calamares, the installer launcher), creates the user you chose,
  and installs GRUB. On UEFI it uses Ubuntu's signed shim/GRUB (EFI directory
  `ubuntu`, which the signed GRUB requires), so installed systems can boot
  with Secure Boot enabled.

### Customizing

- **Add a package:** append it to a `config/packages-lists/*.list.chroot`
  file, run `python3 tools/check-packages.py`, then `sudo ./build.sh --from packages`.
- **Change configuration:** edit a hook or overlay, then `sudo ./build.sh --from customize`.
- **Add an installable module:** add an entry to
  `overlays/usr/lib/primers/modules/module_registry.json`.

## Modules (`primers-install`)

| Module | Contents |
|---|---|
| `devtools` | Python dev tools, Node.js, build-essential, CMake, GDB, Docker |
| `creative` | GIMP, Inkscape, Blender, Kdenlive, Audacity, darktable |
| `gaming` | Steam, controller udev rules, Vulkan tools, extra 32-bit drivers |
| `office` | LibreOffice, Thunderbird, Evince, printing |
| `ai-ml` | Jupyter, NumPy, pandas, scikit-learn, Matplotlib, SciPy, PyTorch |
| `cyber` | nmap, Wireshark, tcpdump, aircrack-ng, John, Hydra, sqlmap, Nikto, gobuster — **only for systems you are authorised to test** |
| `voice` | microphone support + SpeechRecognition for Brain voice commands |
| `macos-compat` | instructions for Darling (not packaged for Ubuntu 22.04) |

## Known limitations

- The live USB needs **Secure Boot disabled** (the ISO uses unsigned GRUB
  from `grub-mkrescue`). Installed systems use the signed boot chain.
- macOS applications are not supported.
- Wine is Ubuntu 22.04's Wine 6.0; many recent games run better through
  Lutris's own Wine/Proton builds.

## Why not live-build?

Ubuntu 22.04's `live-build` is the 2012-era 3.0 branch; its "ubuntu" mode
needs packages that no longer exist in jammy (`gfxboot-theme-ubuntu`,
`syslinux-themes-*`) and Debian-only firmware handling. See
[`docs/decisions/0001-debootstrap-iso-builder.md`](../docs/decisions/0001-debootstrap-iso-builder.md).
