# ⚛ PRIMERS OS 1.0 Genesis

AI-native Linux distribution. Student-driven. Lighter than Ubuntu.
Runs Windows apps, macOS apps, and games — zero configuration.

## Build Requirements

- Ubuntu 22.04 LTS (or WSL2 on Windows)
- 20GB free disk space
- Internet connection (packages download during build)

## Install Build Tools

```bash
sudo apt install -y live-build squashfs-tools xorriso \
  grub-pc-bin grub-efi-amd64-bin mtools isolinux syslinux \
  syslinux-common debootstrap
```

## Build the ISO

```bash
cd primers-distro
chmod +x build.sh clean.sh auto/config auto/build auto/clean
bash build.sh
```

Output: `primers-os-1.0-genesis-amd64.iso`
Build time: 30-90 minutes depending on internet speed.

## Test in QEMU

```bash
# Minimum spec (2GB RAM)
qemu-system-x86_64 -cdrom primers-os-1.0-genesis-amd64.iso \
  -m 2048 -enable-kvm -vga std -net nic -net user

# Full spec (4GB RAM)
qemu-system-x86_64 -cdrom primers-os-1.0-genesis-amd64.iso \
  -m 4096 -enable-kvm -cpu host -smp 4 -vga virtio \
  -net nic -net user
```

## First Boot

The PRIMERS Brain terminal opens automatically on login.

```text
primers          Launch the AI brain
help             Show all commands
status           System health: CPU, memory, disk
gui start        Open dashboard at <http://localhost:5000>
learn suggest    AI suggests your next command
```

## Install Software Modules

```bash
primers-install              List available modules
primers-install gaming       Full gaming stack
primers-install devtools     Dev environment
primers-install creative     GIMP, Blender, OBS
primers-install cyber        Security tools
primers-install ai-ml        PyTorch, Jupyter
primers-install office       LibreOffice
primers-install macos-compat macOS app support
```

## Run Windows Apps

Drop any .exe on the desktop and double-click, or:

```bash
primers-compat program.exe
```

Wine is pre-configured. No setup required.

## Run Games

```bash
primers-install gaming
lutris
```

Install any game through Lutris. DXVK and GameMode are
pre-configured — no manual Proton setup needed.

## What Makes This Different

| Feature                  | PRIMERS OS | Ubuntu | Kali | Windows |
|--------------------------|:----------:|:------:|:----:|:-------:|
| ISO size                 | <800MB     | 4.7GB  | 4.1GB| 5GB+    |
| RAM (minimum)            | 2GB        | 4GB    | 2GB  | 4GB     |
| AI brain built-in        | ✓          | ✗      | ✗    | ✗       |
| Windows apps (zero conf) | ✓          | ✗      | ✗    | native  |
| Student module system    | ✓          | ✗      | ✗    | ✗       |
| Gaming-optimised kernel  | ✓          | ✗      | ✗    | partial |
| Self-learning shell      | ✓          | ✗      | ✗    | ✗       |
