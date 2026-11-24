#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║   PRIMERS OS — ISO Build System v2                           ║
# ║   debootstrap → chroot → squashfs → GRUB hybrid ISO          ║
# ╚══════════════════════════════════════════════════════════════╝
#
# Builds a casper-based live/installable ISO that boots on BIOS and UEFI.
#
#   sudo ./build.sh                    full build
#   sudo ./build.sh --from customize   rebuild from a stage (keeps earlier work)
#   sudo ./build.sh --only image       run a single stage
#   sudo ./build.sh --list             show stages
#
# Stages run in order; each one leaves a stamp in $WORK so an interrupted
# build resumes where it stopped.
#
# Environment:
#   PRIMERS_WORK_DIR   build directory (default: ./work)
#   BUILD_CA_FILE      extra CA certificate trusted *only during the build*
#                      (for builds behind a TLS-inspecting proxy). It is
#                      removed before the image is packed and the build fails
#                      if it is still present.
#   Any variable in config/build.conf.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=config/build.conf
source "$HERE/config/build.conf"

WORK="${PRIMERS_WORK_DIR:-$HERE/work}"
CHROOT="$WORK/chroot"
IMAGE="$WORK/image"
CACHE="$WORK/cache"
OUTPUT="${OUTPUT_DIR:-$HERE}/$ISO_NAME"
LOG="$HERE/build.log"

STAGES=(bootstrap packages customize finalize image)
BUILD_CA_IN_CHROOT="/usr/local/share/ca-certificates/primers-build-ca.crt"
EXCLUDE_PIN="/etc/apt/preferences.d/primers-build-exclude"
MOZILLA_KEY_FPR="35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3"

# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

log()  { printf '\033[96m[BUILD]\033[0m %s\n' "$*"; }
warn() { printf '\033[93m[WARN]\033[0m  %s\n' "$*" >&2; }
die()  { printf '\033[91m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

in_chroot() {
  chroot "$CHROOT" /usr/bin/env -i \
    HOME=/root \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    ${https_proxy:+https_proxy="$https_proxy"} \
    ${http_proxy:+http_proxy="$http_proxy"} \
    ${no_proxy:+no_proxy="$no_proxy"} \
    "$@"
}

apt_in_chroot() {
  in_chroot apt-get -y -q \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    "$@"
}

mount_chroot() {
  mkdir -p "$CHROOT"/{dev/pts,proc,sys,run}
  mountpoint -q "$CHROOT/dev"     || mount --bind /dev "$CHROOT/dev"
  mountpoint -q "$CHROOT/dev/pts" || mount -t devpts devpts "$CHROOT/dev/pts" -o gid=5,mode=620
  mountpoint -q "$CHROOT/proc"    || mount -t proc proc "$CHROOT/proc"
  mountpoint -q "$CHROOT/sys"     || mount -t sysfs sysfs "$CHROOT/sys"
  mountpoint -q "$CHROOT/run"     || mount -t tmpfs tmpfs "$CHROOT/run"
  # Name resolution for apt inside the chroot (restored in finalize)
  rm -f "$CHROOT/etc/resolv.conf"
  cp -L /etc/resolv.conf "$CHROOT/etc/resolv.conf"
}

umount_chroot() {
  [ -d "$CHROOT" ] || return 0
  local m
  for m in run sys proc dev/pts dev; do
    if mountpoint -q "$CHROOT/$m" 2>/dev/null; then
      umount "$CHROOT/$m" 2>/dev/null || umount -l "$CHROOT/$m" || true
    fi
  done
}

restore_resolv_conf() {
  # Installed systems use systemd-resolved behind NetworkManager
  rm -f "$CHROOT/etc/resolv.conf"
  ln -s ../run/systemd/resolve/stub-resolv.conf "$CHROOT/etc/resolv.conf"
}

on_exit() {
  local rc=$?
  umount_chroot
  if [ $rc -ne 0 ]; then
    printf '\033[91m[ERROR]\033[0m Build failed (exit %s). See %s\n' "$rc" "$LOG" >&2
  fi
}

read_package_list() {
  # Strip comments and blank lines from a package list
  sed -e 's/#.*//' -e 's/[[:space:]]\+$//' "$1" | awk 'NF'
}

stamp()      { touch "$WORK/.stamp-$1"; }
has_stamp()  { [ -e "$WORK/.stamp-$1" ]; }
clear_from() {
  local found=0 s
  for s in "${STAGES[@]}"; do
    [ "$s" = "$1" ] && found=1
    [ $found -eq 1 ] && rm -f "$WORK/.stamp-$s"
  done
  [ $found -eq 1 ] || die "Unknown stage: $1 (stages: ${STAGES[*]})"
}

check_host() {
  [ "$(id -u)" -eq 0 ] || die "Run as root: sudo $0 $*"
  local missing=() dep
  for dep in debootstrap mksquashfs xorriso grub-mkrescue mformat chroot gpg curl; do
    command -v "$dep" >/dev/null 2>&1 || missing+=("$dep")
  done
  [ -d /usr/lib/grub/i386-pc ]     || missing+=("grub-pc-bin")
  [ -d /usr/lib/grub/x86_64-efi ]  || missing+=("grub-efi-amd64-bin")
  if [ ${#missing[@]} -gt 0 ]; then
    die "Missing build tools: ${missing[*]}
  Install with:
    sudo apt-get install -y debootstrap squashfs-tools xorriso mtools \\
      grub-pc-bin grub-efi-amd64-bin grub-common gnupg curl"
  fi
  if [ -n "${BUILD_CA_FILE:-}" ] && [ ! -f "$BUILD_CA_FILE" ]; then
    die "BUILD_CA_FILE=$BUILD_CA_FILE does not exist"
  fi
}

# ──────────────────────────────────────────────────────────────
#  Stage 1 — bootstrap: minimal Ubuntu base
# ──────────────────────────────────────────────────────────────

stage_bootstrap() {
  log "Bootstrapping Ubuntu $SUITE ($ARCH) from $MIRROR"
  umount_chroot
  rm -rf "$CHROOT"
  mkdir -p "$CHROOT" "$CACHE/debootstrap"
  debootstrap \
    --arch="$ARCH" \
    --variant=minbase \
    --components="$(echo "$COMPONENTS" | tr ' ' ',')" \
    --cache-dir="$CACHE/debootstrap" \
    "$SUITE" "$CHROOT" "$MIRROR"
}

# ──────────────────────────────────────────────────────────────
#  Stage 2 — packages: kernel, desktop, PRIMERS stack
# ──────────────────────────────────────────────────────────────

write_apt_sources() {
  cat > "$CHROOT/etc/apt/sources.list" <<EOF
deb $MIRROR $SUITE $COMPONENTS
deb $MIRROR $SUITE-updates $COMPONENTS
deb $SECURITY_MIRROR $SUITE-security $COMPONENTS
EOF

  # Keep apt lean inside the image
  cat > "$CHROOT/etc/apt/apt.conf.d/90primers" <<'EOF'
Acquire::Languages "none";
APT::Get::Assume-Yes "true";
EOF

  # Packages that must not land in the image (see config/packages-lists/exclude.list)
  : > "$CHROOT$EXCLUDE_PIN"
  local pkg
  if [ -f "$HERE/config/packages-lists/exclude.list" ]; then
    while read -r pkg; do
      printf 'Package: %s\nPin: release a=*\nPin-Priority: -1\n\n' "$pkg" >> "$CHROOT$EXCLUDE_PIN"
    done < <(read_package_list "$HERE/config/packages-lists/exclude.list")
  fi

  # Never pull snapd: snaps cannot be installed in a chroot and
  # PRIMERS ships Firefox as a .deb from Mozilla's own repository.
  cat > "$CHROOT/etc/apt/preferences.d/no-snapd" <<'EOF'
Package: snapd
Pin: release a=*
Pin-Priority: -10
EOF
}

setup_mozilla_repo() {
  log "Adding Mozilla's APT repository (Firefox .deb)"
  local key="$CACHE/packages.mozilla.org.asc"
  mkdir -p "$CACHE"
  curl -fsSL https://packages.mozilla.org/apt/repo-signing-key.gpg -o "$key.tmp"
  local fpr
  fpr="$(gpg --show-keys --with-colons "$key.tmp" 2>/dev/null | awk -F: '/^fpr:/ {print $10; exit}')"
  [ "$fpr" = "$MOZILLA_KEY_FPR" ] || die "Mozilla signing key fingerprint mismatch: got '$fpr'"
  mv "$key.tmp" "$key"

  install -d -m 0755 "$CHROOT/etc/apt/keyrings"
  install -m 0644 "$key" "$CHROOT/etc/apt/keyrings/packages.mozilla.org.asc"
  echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
    > "$CHROOT/etc/apt/sources.list.d/mozilla.list"
  cat > "$CHROOT/etc/apt/preferences.d/mozilla" <<'EOF'
Package: *
Pin: origin packages.mozilla.org
Pin-Priority: 1000
EOF
}

install_build_ca() {
  [ -n "${BUILD_CA_FILE:-}" ] || return 0
  log "Trusting build CA inside chroot (temporary)"
  install -D -m 0644 "$BUILD_CA_FILE" "$CHROOT$BUILD_CA_IN_CHROOT"
  in_chroot update-ca-certificates >/dev/null 2>&1 || true
}

remove_build_ca() {
  if [ -e "$CHROOT$BUILD_CA_IN_CHROOT" ]; then
    log "Removing temporary build CA from chroot"
    rm -f "$CHROOT$BUILD_CA_IN_CHROOT"
    in_chroot update-ca-certificates --fresh >/dev/null 2>&1 || true
  fi
}

stage_packages() {
  mount_chroot
  write_apt_sources

  # Do not start services while installing packages
  printf '#!/bin/sh\nexit 101\n' > "$CHROOT/usr/sbin/policy-rc.d"
  chmod +x "$CHROOT/usr/sbin/policy-rc.d"

  # 32-bit userland for Wine and games
  in_chroot dpkg --add-architecture i386

  log "Updating package index"
  apt_in_chroot update
  apt_in_chroot install ca-certificates gnupg curl
  install_build_ca

  setup_mozilla_repo
  apt_in_chroot update
  apt_in_chroot dist-upgrade

  log "Installing kernel: $KERNEL_PACKAGE"
  apt_in_chroot install "$KERNEL_PACKAGE" casper

  local list
  for list in "$HERE"/config/packages-lists/*.list.chroot; do
    log "Installing package list: $(basename "$list")"
    # shellcheck disable=SC2046
    apt_in_chroot install $(read_package_list "$list")
  done

  if [ -f "$HERE/config/packages-lists/exclude.list" ]; then
    local installed=() pkg
    while read -r pkg; do
      if in_chroot dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
        installed+=("$pkg")
      fi
    done < <(read_package_list "$HERE/config/packages-lists/exclude.list" | sed 's/:.*//')
    if [ ${#installed[@]} -gt 0 ]; then
      log "Purging excluded packages: ${installed[*]}"
      apt_in_chroot purge "${installed[@]}"
    fi
  fi

  apt_in_chroot autoremove --purge
}

# ──────────────────────────────────────────────────────────────
#  Stage 3 — customize: overlays, PRIMERS brain, installer, hooks
# ──────────────────────────────────────────────────────────────

stage_customize() {
  mount_chroot

  log "Applying filesystem overlays"
  cp -a "$HERE/overlays/." "$CHROOT/"

  log "Installing PRIMERS brain -> /usr/share/primers/brain"
  rm -rf "$CHROOT/usr/share/primers/brain"
  install -d -m 0755 "$CHROOT/usr/share/primers/brain"
  tar -C "$REPO_ROOT/primers-os" \
      --exclude='./logs' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='./tests' --exclude='./.pytest_cache' --exclude='./CHANGELOG.md' \
      -cf - . | tar -C "$CHROOT/usr/share/primers/brain" -xf -
  chown -R root:root "$CHROOT/usr/share/primers"
  find "$CHROOT/usr/share/primers/brain" -type d -exec chmod 0755 {} +
  find "$CHROOT/usr/share/primers/brain" -type f -exec chmod 0644 {} +

  log "Installing Primers OS brand assets -> /usr/share/primers/branding"
  rm -rf "$CHROOT/usr/share/primers/branding"
  install -d -m 0755 "$CHROOT/usr/share/primers/branding"
  cp -r "$REPO_ROOT/branding/primers-os-logo/png" "$REPO_ROOT/branding/primers-os-logo/svg" \
        "$CHROOT/usr/share/primers/branding/"
  find "$CHROOT/usr/share/primers/branding" -type d -exec chmod 0755 {} +
  find "$CHROOT/usr/share/primers/branding" -type f -exec chmod 0644 {} +

  log "Installing Primers Lite Bee -> /usr/share/primers/lite-bee"
  rm -rf "$CHROOT/usr/share/primers/lite-bee"
  install -d -m 0755 "$CHROOT/usr/share/primers/lite-bee"
  tar -C "$REPO_ROOT/primers-lite-bee" --exclude='__pycache__' --exclude='*.pyc' -cf - litebee \
    | tar -C "$CHROOT/usr/share/primers/lite-bee" -xf -
  install -m 0755 "$REPO_ROOT/primers-lite-bee/lite-bee" "$CHROOT/usr/bin/lite-bee"
  find "$CHROOT/usr/share/primers/lite-bee" -type d -exec chmod 0755 {} +
  find "$CHROOT/usr/share/primers/lite-bee" -type f -exec chmod 0644 {} +

  log "Installing Calamares configuration -> /etc/calamares"
  rm -rf "$CHROOT/etc/calamares"
  install -d -m 0755 "$CHROOT/etc/calamares"
  cp -a "$HERE/installer/calamares/." "$CHROOT/etc/calamares/"

  log "Configuring live session (casper)"
  cat > "$CHROOT/etc/casper.conf" <<EOF
# PRIMERS OS live session — read by casper at boot
export USERNAME="$LIVE_USER"
export USERFULLNAME="$LIVE_USER_FULLNAME"
export HOST="$LIVE_HOSTNAME"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="PRIMERS"
EOF

  local hook
  for hook in "$HERE"/config/hooks/chroot/*.hook.chroot; do
    log "Running hook: $(basename "$hook")"
    install -m 0755 "$hook" "$CHROOT/tmp/primers-hook"
    in_chroot \
      PRIMERS_NAME="$PRIMERS_NAME" \
      PRIMERS_VERSION="$PRIMERS_VERSION" \
      PRIMERS_CODENAME="$PRIMERS_CODENAME" \
      LIVE_USER="$LIVE_USER" \
      /bin/bash /tmp/primers-hook
    rm -f "$CHROOT/tmp/primers-hook"
  done
}

# ──────────────────────────────────────────────────────────────
#  Stage 4 — finalize: initramfs, cleanup, security checks
# ──────────────────────────────────────────────────────────────

stage_finalize() {
  mount_chroot

  log "Regenerating initramfs (casper)"
  in_chroot update-initramfs -u -k all

  log "Cleaning chroot"
  apt_in_chroot clean
  rm -rf "$CHROOT"/var/lib/apt/lists/*
  rm -rf "$CHROOT"/tmp/* "$CHROOT"/var/tmp/*
  rm -f  "$CHROOT"/root/.bash_history
  rm -f  "$CHROOT/usr/sbin/policy-rc.d"
  rm -f  "$CHROOT$EXCLUDE_PIN"
  rm -f  "$CHROOT"/var/log/*.log "$CHROOT"/var/log/apt/* 2>/dev/null || true
  # Each installed machine must generate its own machine-id
  : > "$CHROOT/etc/machine-id"
  rm -f "$CHROOT/var/lib/dbus/machine-id"
  # Host SSH keys must never be shared between installs
  rm -f "$CHROOT"/etc/ssh/ssh_host_*

  remove_build_ca
  umount_chroot
  restore_resolv_conf

  # Hard security gate: nothing from the build host may leak into the image
  if [ -e "$CHROOT$BUILD_CA_IN_CHROOT" ]; then
    die "Build CA still present in chroot — refusing to continue"
  fi
  if [ -n "${BUILD_CA_FILE:-}" ] && \
     grep -qF "$(sed -n '2p' "$BUILD_CA_FILE")" "$CHROOT/etc/ssl/certs/ca-certificates.crt" 2>/dev/null; then
    die "Build CA still present in the system trust store — refusing to continue"
  fi
}

# ──────────────────────────────────────────────────────────────
#  Stage 5 — image: squashfs + GRUB (BIOS + UEFI) hybrid ISO
# ──────────────────────────────────────────────────────────────

write_grub_cfg() {
  cat > "$IMAGE/boot/grub/grub.cfg" <<EOF
# PRIMERS OS live boot menu
search --no-floppy --set=root --file /casper/vmlinuz

insmod all_video
insmod gfxterm
insmod png
set gfxmode=auto
terminal_output gfxterm

if [ -s /boot/grub/themes/primers/theme.txt ]; then
  for f in /boot/grub/themes/primers/*.pf2; do loadfont "\$f"; done
  set theme=/boot/grub/themes/primers/theme.txt
fi

set default=0
set timeout=5

menuentry "Try or Install $PRIMERS_NAME $PRIMERS_VERSION $PRIMERS_CODENAME" {
  linux /casper/vmlinuz boot=casper quiet splash ---
  initrd /casper/initrd
}
menuentry "$PRIMERS_NAME (safe graphics)" {
  linux /casper/vmlinuz boot=casper nomodeset ---
  initrd /casper/initrd
}
menuentry "$PRIMERS_NAME (load into RAM)" {
  linux /casper/vmlinuz boot=casper toram quiet splash ---
  initrd /casper/initrd
}
menuentry "$PRIMERS_NAME (check disc for defects)" {
  linux /casper/vmlinuz boot=casper integrity-check quiet splash ---
  initrd /casper/initrd
}
if [ "\$grub_platform" = "efi" ]; then
  menuentry "UEFI firmware settings" { fwsetup }
else
  menuentry "Boot from first hard disk" { set root=(hd0); chainloader +1 }
fi
EOF
}

stage_image() {
  [ -x "$CHROOT/bin/bash" ] || die "No chroot found — run the earlier stages first"
  umount_chroot

  log "Preparing ISO tree"
  rm -rf "$IMAGE"
  mkdir -p "$IMAGE"/{casper,.disk,boot/grub/themes/primers}

  local vmlinuz initrd
  vmlinuz="$(find "$CHROOT/boot" -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -n1)"
  initrd="$(find "$CHROOT/boot" -maxdepth 1 -name 'initrd.img-*' | sort -V | tail -n1)"
  [ -n "$vmlinuz" ] && [ -n "$initrd" ] || die "Kernel or initrd missing from chroot/boot"
  cp "$vmlinuz" "$IMAGE/casper/vmlinuz"
  cp "$initrd"  "$IMAGE/casper/initrd"

  log "Writing manifests"
  chroot "$CHROOT" dpkg-query -W --showformat='${Package} ${Version}\n' > "$IMAGE/casper/filesystem.manifest"
  printf '%s\n' casper calamares > "$IMAGE/casper/filesystem.manifest-remove"

  log "Compressing root filesystem (squashfs, $SQUASHFS_COMP) — this takes a while"
  rm -f "$IMAGE/casper/filesystem.squashfs"
  local comp_opts=(-comp "$SQUASHFS_COMP")
  [ "$SQUASHFS_COMP" = "xz" ] && comp_opts+=(-Xbcj x86 -b 1M)
  mksquashfs "$CHROOT" "$IMAGE/casper/filesystem.squashfs" \
    "${comp_opts[@]}" -noappend -wildcards \
    -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*'
  du -sx --block-size=1 "$CHROOT" | cut -f1 > "$IMAGE/casper/filesystem.size"

  echo "$PRIMERS_NAME $PRIMERS_VERSION \"$PRIMERS_CODENAME\" - Release $ARCH ($(date -u +%Y%m%d))" > "$IMAGE/.disk/info"
  touch "$IMAGE/.disk/base_installable"
  echo "full_cd/single" > "$IMAGE/.disk/cd_type"

  log "Writing GRUB configuration"
  # Theme + fonts generated inside the chroot (hook 0050)
  if [ -f "$CHROOT/usr/share/grub/themes/primers/theme.txt" ]; then
    cp -a "$CHROOT/usr/share/grub/themes/primers/." "$IMAGE/boot/grub/themes/primers/"
  fi
  write_grub_cfg

  (cd "$IMAGE" && find . -type f ! -name md5sum.txt ! -path './boot/grub/*' -print0 \
     | xargs -0 md5sum > md5sum.txt)

  log "Creating hybrid ISO (BIOS + UEFI): $OUTPUT"
  rm -f "$OUTPUT"
  grub-mkrescue -o "$OUTPUT" "$IMAGE" -- \
    -volid "$ISO_VOLUME" \
    -joliet on \
    -publisher "Primers Organisation" \
    -application_id "$PRIMERS_NAME $PRIMERS_VERSION $PRIMERS_CODENAME"

  (cd "$(dirname "$OUTPUT")" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")
}

# ──────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────

usage() {
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  local from="" only=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --from)  from="${2:?--from needs a stage}"; shift 2 ;;
      --only)  only="${2:?--only needs a stage}"; shift 2 ;;
      --list)  printf '%s\n' "${STAGES[@]}"; exit 0 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown option: $1 (see --help)" ;;
    esac
  done

  check_host "$@"
  mkdir -p "$WORK"
  trap on_exit EXIT

  echo "╔══════════════════════════════════════════╗"
  echo "║   $PRIMERS_NAME — ISO Build System v2       ║"
  echo "╚══════════════════════════════════════════╝"
  log "Work dir: $WORK"

  [ -n "$from" ] && clear_from "$from"
  if [ -n "$only" ]; then
    clear_from "$only"
  fi

  local s start
  for s in "${STAGES[@]}"; do
    if [ -n "$only" ] && [ "$s" != "$only" ]; then
      continue
    fi
    if has_stamp "$s"; then
      log "Stage '$s' already done — skipping (use --from $s to redo)"
      continue
    fi
    start=$(date +%s)
    log "━━━ Stage: $s ━━━"
    "stage_$s"
    stamp "$s"
    log "Stage '$s' finished in $(( $(date +%s) - start ))s"
  done

  if [ -f "$OUTPUT" ]; then
    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║   BUILD COMPLETE                         ║"
    echo "╚══════════════════════════════════════════╝"
    echo "  Output: $OUTPUT"
    echo "  Size:   $(du -h "$OUTPUT" | cut -f1)"
    echo "  SHA256: $(cut -d' ' -f1 "$OUTPUT.sha256")"
    echo ""
    echo "  Test (BIOS):  qemu-system-x86_64 -m 4096 -smp 2 -enable-kvm -cdrom $ISO_NAME"
    echo "  Test (UEFI):  qemu-system-x86_64 -m 4096 -smp 2 -enable-kvm -bios /usr/share/ovmf/OVMF.fd -cdrom $ISO_NAME"
  fi
}

main "$@" 2>&1 | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
