# ⚛ PRIMERS OS 1.0 Genesis

An AI-native Linux desktop built on **Ubuntu 22.04 LTS**. Lightweight Openbox
desktop, Windows apps and games out of the box, and the **PRIMERS Brain** — a
system controller you talk to in plain language that monitors, secures and
learns how you use your computer.

This repository contains both halves of the OS:

| Directory | What it is |
|---|---|
| [`primers-os/`](primers-os/README.md) | **PRIMERS Brain** — the Python system controller (CLI shell, web dashboard, AI engines, plugins) |
| [`primers-lite-bee/`](primers-lite-bee/README.md) | **Primers Lite Bee** — our fast, data-saving browser for 2G, LTE and Wi-Fi |
| [`primers-distro/`](primers-distro/README.md) | **The distribution** — ISO build system, desktop configuration, installer, module system |

---

## Get PRIMERS OS

**Download:** tagged releases (`v*`) are built by GitHub Actions and attached to
the [Releases page](https://github.com/Jothankato05/primers-os/releases).

**Or build the ISO yourself** (Ubuntu 22.04/24.04 host, ~20 GB free disk):

```bash
sudo apt-get install -y debootstrap squashfs-tools xorriso mtools grub-pc-bin grub-efi-amd64-bin grub-common gnupg curl
```

```bash
cd primers-distro && sudo ./build.sh
```

Output: `primers-distro/primers-os-1.0-genesis-amd64.iso` (~2.2 GB). Details,
stages and options: [primers-distro/README.md](primers-distro/README.md).

**Try it in a VM:**

```bash
qemu-system-x86_64 -enable-kvm -m 4096 -smp 2 -cdrom primers-distro/primers-os-1.0-genesis-amd64.iso
```

**Install:** write the ISO to a USB stick (balenaEtcher, Rufus in DD mode, or
`dd`), boot it, and double-click **Install PRIMERS OS** on the desktop. The
installer handles BIOS and UEFI machines, offers full-disk encryption, and the
installed system supports Secure Boot (the live USB itself needs Secure Boot
turned off).

---

## What you get

| | |
|---|---|
| **PRIMERS Brain** | Opens on login (or `Super+Enter`). `status`, `ps`, `threats`, `advise`, `math 2^10`… or just ask: *"how is my system?"*, *"am I safe?"*, *"any advice?"* |
| **Ask Primers** | Offline answers about Primers from the built-in knowledge base: *"what is Veltis One?"*, *"who founded Primers?"* — emergencies first (112) |
| **Primers Lite Bee** | Default browser. Detects Wi-Fi / LTE / 2G and switches between Full, Lite and Ultra data modes; ads and trackers blocked in the engine; data meter in MB (and ₦); offline saving, reader mode, session restore |
| **Desktop** | Openbox + tint2 panel, PCManFM, dark theme, LightDM login |
| **Windows apps** | Wine (64- and 32-bit); double-click any `.exe` or `primers-compat app.exe` |
| **Gaming** | Lutris, GameMode, MangoHud, Mesa Vulkan (64/32-bit); `primers-install gaming` adds Steam |
| **Apps** | Primers Lite Bee, Firefox (Mozilla's official .deb), VLC, OBS Studio, text editor, image viewer, archive manager |
| **Modules** | `primers-install devtools \| creative \| gaming \| office \| ai-ml \| cyber \| voice` |
| **Security** | Firewall on, CPU mitigations on, automatic security updates, AppArmor, no shared passwords — the live user exists only in the live session |
| **Kernel** | Ubuntu HWE kernel (6.8) for recent GPUs and Wi-Fi, zram swap, performance governor on AC power |

## Repository layout

```
primers-os/            PRIMERS Brain (Python 3.10+)
  main.py              entry point: `primers`, `primers status`, `primers -c "cmd"`
  core/ ai/ services/  monitoring, security, learning, automation, math, GPA, graph…
  interface/           CLI shell, web dashboard, voice
  tests/               pytest suite
  knowledge/           PRIMERS_KNOWLEDGE.md — the system knowledge layer (Ask Primers)
primers-lite-bee/      Primers Lite Bee browser (Python + GTK + WebKit)
primers-distro/        ISO build system
  build.sh             debootstrap → chroot → squashfs → hybrid BIOS/UEFI ISO
  config/              build.conf, package lists, chroot hooks
  overlays/            files copied into the OS (launchers, desktop config, module registry)
  installer/calamares/ installer configuration and branding
  tools/               check-packages.py (validates every package name)
branding/              official Primers OS logo pack (SVG + PNG) — source of all OS artwork
docs/decisions/        architecture decision records
.github/workflows/     CI (tests + lint) and ISO build/release
```

## Development

```bash
cd primers-os
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q tests
python3 main.py
```

CI runs the tests on Python 3.10 (what the OS ships) and 3.12, lints every
shell script and config file, and checks that every package exists in
Ubuntu 22.04. Pushing a `v*` tag builds the ISO and publishes a release.

## Security note

The Security Engine and Cyber Intelligence module are **strictly defensive**:
they watch local processes, connections and listening ports, raise alerts and
explain them. Nothing is ever terminated without your explicit confirmation,
and voice commands can only run read-only actions. The web dashboard is
read-only and listens on `localhost` only.

## Roadmap

- **1.0 Genesis** (this release) — installable OS, Brain with learning, automation, dashboard, plugins
- **Next** — Secure Boot for the live USB, local speech recognition, graphical settings for the Brain, OTA module catalogue
