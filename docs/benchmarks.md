# PRIMERS OS performance benchmarks

How fast PRIMERS OS 1.0 starts, how much memory it uses and how long a
candidate waits for the exam, on the smallest PC it supports, measured
against the design targets. Every number here comes from the release
workflow's `performance` VM test (`primers-distro/tests/vm/run_vm_tests.py
performance`); each run's raw results are in its `vm-test-results`
artifact (`performance/performance.json`).

## Targets

| What | Target |
|---|---|
| Cold boot, power-on to login screen | < 30 s on a hard disk, < 15 s on an SSD |
| Memory in use when idle | < 600 MB |
| Candidate signs in → exam page on screen | < 3 s |

## The test PC

- A VM with **2 GB of memory and 2 CPU cores** (KVM on a GitHub-hosted
  runner, AMD EPYC 7763), PRIMERS OS installed on its disk (legacy BIOS,
  Lab Mode on).
- **Hard disk profile:** the disk is seen as rotating (7200 rpm) and
  limited to ~120 I/O operations and 110 MB/s, like a desktop hard disk.
- **SSD profile:** seen as solid-state, ~20000 I/O operations and 500 MB/s,
  like a SATA SSD.
- Each profile is a **cold boot**: the VM is shut down and switched on, so
  nothing is in its memory.

What is measured:

- **Power-on to login screen:** from switching the VM on to the login
  screen's process running, timed from outside the VM (firmware, boot
  loader, kernel, services). This is what a person waits.
- **Kernel to login screen:** from the kernel starting to the login screen
  (the OS's own part).
- **Idle memory:** `MemTotal − MemAvailable` after 2 minutes idle at the
  login screen, and at the lab account's desktop.
- **Sign-in to exam page:** from the candidate's session opening to the
  exam page shown in the kiosk (the kiosk logs each step), with Exam Mode
  started beforehand, as invigilators do.

## Results

Run 33 is before any tuning; run 36 is after the fixes below
(commits 66053ef and 4ced0c7).

| | Hard disk, before | **Hard disk, now** | SSD, before | **SSD, now** | Target |
|---|---|---|---|---|---|
| Power-on to login screen | 126 s | **72.9 s** ✗ | 16.9 s | **8.8 s** ✓ | 30 s / 15 s |
| Kernel to login screen | 36.4 s¹ | **30.5 s** ✗ | 5.8 s¹ | **4.4 s** ✓ | |
| Idle memory, login screen | 354 MB | **333 MB** ✓ | 351 MB | **324 MB** ✓ | 600 MB |
| Idle memory, lab desktop | 425 MB | **437 MB** ✓ | 455 MB | **437 MB** ✓ | 600 MB |
| Sign-in to exam page | 7.2 s² | **1.7 s** ✓ | 1.2 s² | **1.0 s** ✓ | 3 s |

¹ Run 33 measured until every service had started (graphical.target);
the login screen can appear a little earlier. ² Run 33's own figure (11 s)
was wrong: the guest agent logs the test's commands, and the test counted
its own polling. These are the step times from run 34 (before the
pre-warm).

Where the sign-in time goes now (seconds after the session opens):

| Step | Hard disk | SSD |
|---|---|---|
| Exam session started | 0.34 | 0.34 |
| Exam browser window open | 1.22 | 0.82 |
| Exam server answered | 1.50 | 0.99 |
| Exam page shown | **1.67** | **1.00** |

Memory at the idle lab desktop (437 MB in use, of 1968 MB): the largest
processes are Xorg (84 MB), the Lab Mode sign-in notice (60 MB, until the
student closes it), the Bluetooth, network and sound tray icons (52, 48,
44 MB), the file manager / desktop (43 MB) and the update checker (24 MB).

## What was fixed

| Fix | Effect |
|---|---|
| The initramfs carried AMD/NVIDIA graphics and data-centre network drivers and firmware (179 MB) that the boot loader reads before the kernel starts. A hook (`/etc/initramfs-tools/hooks/primers-trim`) leaves them out; they load from the system a few seconds later. Every disk, USB, keyboard and Intel graphics driver stays; the build checks both. | 179 → 82 MB; ISO 2.09 → 1.90 GB; power-on on the hard disk 126 → 73 s |
| No boot menu wait (it was 5 s on every boot). Shown for 10 s when another system is installed (Ubuntu's os-prober script) or with Shift/Esc; 10 s after an interrupted boot (was 30). The installer's settings match. | −5 s on every boot |
| Services a lab PC doesn't use are no longer started at boot (packages kept; D-Bus starts blueman's and Avahi's helpers if anything asks): winbind, networkd-dispatcher, avahi-daemon, blueman-mechanism (22 s on the hard disk, in the way of the login screen), Ubuntu Pro units, apport. The fleet agent no longer starts the wait-for-network at every boot. | kernel to login 36 → 30 s (hard disk), 5.8 → 4.4 s (SSD) |
| While an exam is on, the exam browser (its programs, libraries, Python bindings; ~220 MB of cache the kernel drops when memory is needed) is read into memory after the login screen is up and after `primers-exam start`, at the lowest CPU and disk priority (`primers-exam-prewarm.service`; 11.8 s on the hard disk, 2.6 s on the SSD). | sign-in to exam page 7.2 → 1.7 s on the hard disk |

## Misses and the plan

**1. Power-on to login on a hard disk: 72.9 s (target 30 s).** Of this,
~42 s pass before the kernel starts: the firmware and the boot loader
reading the kernel (15 MB) and the initramfs (82 MB). The test's hard disk
counts every small read the boot loader makes against its ~120 operations
a second, which is right for scattered reads but pessimistic for one long
file: a real 7200 rpm disk reads 100 MB in about a second. The figure for a
real hard disk is therefore not known from this test.

- Measure on real lab PCs with hard disks: `benchmark` in the Brain
  reports boot to login from the boot's own record (on UEFI PCs including
  the firmware and boot loader; pilot guide, "Collect proof points"), and a
  stopwatch from the power button to the login screen gives the rest.
- Make the initramfs much smaller on installed PCs: build it for the PC's
  own hardware (`MODULES=dep`) at install time; expected ~25-35 MB.
  Needs an ADR and tests on real hardware first: an initramfs built for one
  PC may not boot if its disk is moved to a different PC.

**2. Kernel to login screen on a hard disk: 30.5 s (target 30 s).** The
login screen waits for:

| Step | Hard disk |
|---|---|
| Lab Mode's boot reset (`primers-lab-reset`, ordered before the login screen so a power cut can't leave a student's files for the next one) | 11.5 s, mostly Python starting from a cold disk |
| Writing the journal to disk (`systemd-journal-flush`) | 6.3 s |
| NetworkManager (user sessions wait for the network target) | 5.8 s |

- Lab Mode's boot reset: do the locks first (they must be in place before
  the login screen: ADR 0004) and wipe the lab account without waiting for
  Python, or skip the wipe when the account is already pristine (it is
  wiped again at every sign-in anyway).
- Journal: cap its size on disk (`SystemMaxUse`), so the flush has less to
  write; the exam log keeps its own durable copy (ADR 0004).
- Then measure again; on the SSD the same boot takes 4.4 s.

**Not measured yet:** real lab hardware (CPU, disk and graphics differ
from a cloud VM: the pilot's `benchmark` reports fill this in); UEFI boots
(the firmware's own time differs); a PC with 4 GB or more; Wi-Fi.

## Reproducing

On GitHub: Actions → **Build and Release PRIMERS OS ISO** → Run workflow on
the working branch with **scenario: performance**. It builds the image and
runs only this test; such a run keeps no ISO and can never publish a release.

On a machine with KVM:

```bash
sudo PRIMERS_WORK_DIR=/mnt/primers-work ./primers-distro/build.sh
python3 primers-distro/tests/vm/run_vm_tests.py performance --installer script \
    --iso primers-distro/primers-os-1.0-genesis-amd64.iso --out vm-results/performance
```

It needs KVM for meaningful times (under software emulation everything is
several times slower; the memory figures still hold).
