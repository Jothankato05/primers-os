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
sudo apt-get install -y debootstrap squashfs-tools xorriso mtools gnupg curl
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
| `customize` | copy `overlays/`, the PRIMERS Brain, Primers Lite Bee and the installer config; run `config/hooks/chroot/*.hook.chroot` |
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
    0080-configure-browser      Primers Lite Bee icons, default browser, checks
    0090-campus-modes           Lab, Study and Exam Mode checks (all off in the image)
overlays/                       copied verbatim into the OS root
  usr/bin/primers               launches the brain
  usr/bin/primers-terminal      brain in a terminal window (falls back to a shell)
  usr/bin/primers-install       module installer
  usr/bin/primers-compat        Windows program launcher (Wine)
  usr/bin/primers-lab           Lab Mode for shared computers
  usr/bin/primers-study         Study Mode focus timer
  usr/bin/primers-exam          Exam Mode (kiosk + firewall for computer-based tests)
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

### Data Saver (system updates)

Background downloads — the daily package-list refresh, automatic security
upgrades and firmware metadata refresh — are postponed while NetworkManager
reports the connection as **metered** (mobile data and phone hotspots that
announce themselves; you can also mark any connection metered in its
settings). They run on the next Wi-Fi/Ethernet connection. The gate is
`/usr/lib/primers/unmetered-network`, wired in as `ExecCondition=` drop-ins
under `/etc/systemd/system/*.service.d/50-primers-data-saver.conf`.
`unattended-upgrades` also applies its own metered check.

Allow background downloads on metered networks:

```bash
sudo mkdir -p /etc/primers && sudo touch /etc/primers/updates-on-metered
```

`datasaver` in the PRIMERS Brain shows the current state.

### Lab Mode (shared computers)

For lab and library PCs that many students use. It is off by default; turn
it on, on each machine:

```bash
sudo primers-lab enable
```

then **restart the computer** (LightDM reads its configuration only when it
starts, so the lab account can sign in only after a restart, never without
the wipe).

This creates a `lab` account that signs in from the login screen without a
password and is never an administrator (its password is locked, so it can't
be used on a text console, over SSH or with `su`). Its home folder is deleted
and rebuilt from a template **before every session, after every session and
at every boot**, together with its files in `/tmp`, `/var/tmp` and
`/dev/shm`, its crontab and mail, and Wi-Fi profiles only it could use.
Students see a notice at sign-in, and `lab` in the PRIMERS Brain explains it.

- **Template:** `/etc/primers/lab-skel` if it exists, otherwise `/etc/skel`
  (or `--template DIR`). Put the lab's wallpaper, bookmarks and shortcuts
  there; it must be owned by root.
- **Other accounts are untouched.** Staff keep normal accounts on the same
  machine.
- **Safety:** it only ever wipes the account it created (name and UID are
  recorded in `/etc/primers/lab.conf`), and only if that account is still an
  ordinary user with home `/home/<name>` in no admin group. If a check or the
  wipe fails, LightDM refuses the lab sign-in rather than show the previous
  student's files; the reason is in the system log (`journalctl -t primers-lab`).
- **Wiring:** LightDM `session-setup-script`/`session-cleanup-script`
  (`/etc/lightdm/lightdm.conf.d/60-primers-lab.conf`) and
  `primers-lab-reset.service` at boot, before logins are allowed.

```bash
primers-lab status          # on or off, last reset
sudo primers-lab reset      # wipe the lab account now (ends its session)
sudo primers-lab disable    # turn it off and delete the lab account
```

### Exam Mode (computer-based tests)

Runs on top of Lab Mode. The invigilator starts an exam on each PC:

```bash
sudo primers-exam start https://cbt.example.edu.ng --allow cdn.example.edu.ng
```

While it runs, signing in to the shared lab account opens **only the exam
site**, full screen in Primers Lite Bee: no address bar, tabs, menus,
downloads, file picker, printing, developer tools, key shortcuts or other
programs, and a **Finish exam** button that signs the candidate out
(`/etc/X11/Xsession.d/98primers-exam` replaces whatever session was picked;
the only login session in the image is Openbox, so there is no other to pick).

- **Network:** an nftables table (`inet primers_exam`) lets the lab account
  reach only the exam servers' web ports; every other connection from that
  account is refused, whatever program makes it. Other accounts are not
  affected, and ufw reloads don't touch it. Add any other server the exam
  site loads from with `--allow`. Addresses are refreshed at boot and at
  every exam sign-in; if the firewall can't be set up, the exam session is
  refused.
- **USB drives** can't be mounted in the lab account (polkit).
- **Log:** sessions, pages visited, blocked pages and "finished" are logged
  under `primers-exam`: `sudo primers-exam log`.
- Lab Mode still wipes the account before and after every session.

```bash
primers-exam status        # running? firewall and USB block in place?
sudo primers-exam log      # what happened during this exam
sudo primers-exam stop     # end the exam (open exam sessions close)
```

### Study Mode (focus timer)

Any user can start a focus session: `study 25` in the PRIMERS Brain,
`primers-study start 25`, or right-click the desktop › **Study Mode**. While
it runs:

- **Primers Lite Bee pauses distracting sites** (social media, video, games
  and betting) and shows how long is left instead. Typed and clicked links
  are stopped before any data is spent; embedded players and redirects are
  caught too. Add sites, or allow one (`-youtube.com`), in
  `~/.config/primers/study-sites`.
- **The panel shows the minutes left** (`/usr/lib/primers/study-panel`).
- **A notice says when the session is over.** `study stop` ends it early.

The session is a small per-user file, `~/.local/state/primers/study`.
Firefox is not filtered; Study Mode is a focus aid, not a lockdown (that is
Exam Mode's job).

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

### Boot chain

The ISO boots the same way Ubuntu's does:

- **UEFI (Secure Boot on or off):** Microsoft-signed shim → Canonical-signed
  GRUB (`gcdx64.efi.signed`) → Canonical-signed kernel. Verified in QEMU with
  Secure Boot enforced (Microsoft keys enrolled); an unsigned GRUB is refused
  by the same firmware.
- **BIOS:** GRUB 2.06 core image built from the image's own `grub-pc-bin`.
- **Media:** El Torito entries for DVDs, plus an EFI system partition and
  hybrid MBR so the ISO can be written straight to a USB stick.

## Known limitations

- macOS applications are not supported.
- Wine is Ubuntu 22.04's Wine 6.0; many recent games run better through
  Lutris's own Wine/Proton builds.

## Why not live-build?

Ubuntu 22.04's `live-build` is the 2012-era 3.0 branch; its "ubuntu" mode
needs packages that no longer exist in jammy (`gfxboot-theme-ubuntu`,
`syslinux-themes-*`) and Debian-only firmware handling. See
[`docs/decisions/0001-debootstrap-iso-builder.md`](../docs/decisions/0001-debootstrap-iso-builder.md).
