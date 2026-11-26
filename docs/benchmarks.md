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
  runner: an AMD EPYC 7763 or 9V74, whichever the run gets), PRIMERS OS installed on its disk (legacy BIOS,
  Lab Mode on).
- **Hard disk profile:** the disk is seen as rotating (7200 rpm) and
  limited to ~120 I/O operations and 110 MB/s, like a desktop hard disk.
- **SSD profile:** seen as solid-state, ~20000 I/O operations and 500 MB/s,
  like a SATA SSD.
- Each profile is booted **cold five times** (`PRIMERS_PERF_BOOTS`, default
  5): the VM is shut down and switched on, so nothing is in its memory. The
  results give the median and the worst boot, and every boot's figures.

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

Run 33 is before any tuning; run 44 is the code of v1.0.0-rc1; run 47 is
the working branch with the boot changes (commit 1c07b57), with **five cold
boots per disk profile**: the median, and the worst of the five in
brackets. Run 50 (commit 1dbb334, the same boot path, a full release run)
measured another five boots per profile, below. Memory and sign-in to exam
are measured once per profile, after the boots.

| | Run 33, before | Run 44, v1.0.0-rc1 | **Run 47, now: median (worst)** | Target |
|---|---|---|---|---|
| Hard disk: power-on to login screen | 126 s | 72.9 s | **69.1 s (69.7 s)** ✗ | 30 s |
| Hard disk: kernel to login screen | 36.4 s¹ | 31.9 s | **28.8 s (29.8 s)** | |
| SSD: power-on to login screen | 16.9 s | 8.9 s | **8.9 s (8.9 s)** ✓ | 15 s |
| SSD: kernel to login screen | 5.8 s¹ | 5.0 s | **4.5 s (4.5 s)** | |
| Idle memory, login screen (hard disk / SSD) | 354 / 351 MB | 333 / 321 MB | **328 / 320 MB** ✓ | 600 MB |
| Idle memory, lab desktop (hard disk / SSD) | 425 / 455 MB | 447 / 434 MB | **452 / 419 MB** ✓ | 600 MB |
| Sign-in to exam page (hard disk / SSD) | 7.2 / 1.2 s² | 1.62 / 0.81 s | **1.66 / 0.85 s** ✓ | 3 s |

The five boots of run 47, in seconds:

| | Boot 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Hard disk: power-on to login screen | 68.3 | 68.8 | 69.1 | 69.7 | 69.3 |
| Hard disk: kernel to login screen | 27.0 | 28.8 | 28.9 | 29.8 | 28.0 |
| SSD: power-on to login screen | 8.8 | 8.9 | 8.9 | 8.8 | 8.9 |
| SSD: kernel to login screen | 4.3 | 4.5 | 4.5 | 4.4 | 4.5 |

And of run 50 (the same boot path; median, worst):

| | Boot 1 | 2 | 3 | 4 | 5 | Median | Worst |
|---|---|---|---|---|---|---|---|
| Hard disk: power-on to login screen | 68.6 | 69.1 | 69.4 | 69.3 | 72.9 | 69.3 | 72.9 |
| Hard disk: kernel to login screen | 28.2 | 29.3 | 29.0 | 27.9 | 30.8 | 29.0 | **30.8** |
| SSD: power-on to login screen | 8.9 | 8.9 | 8.8 | 8.8 | 8.8 | 8.8 | 8.9 |
| SSD: kernel to login screen | 4.6 | 4.4 | 4.5 | 4.4 | 4.5 | 4.5 | 4.6 |

Over the ten hard-disk boots of runs 47 and 50, kernel to login screen was
27.0 to 30.8 s: the median is under 30 s, one boot in ten was 0.8 s over.

¹ Run 33 measured until every service had started (graphical.target);
the login screen can appear a little earlier. ² Run 33's own figure (11 s)
was wrong: the guest agent logs the test's commands, and the test counted
its own polling. These are the step times from run 34 (before the
pre-warm).

### Every measurement run

Measurement runs used to be made on separate branches; they are now made
on the working branch with the workflow's `scenario: performance` input
(see Reproducing). Each run's raw results stay in its `vm-test-results`
artifact (`performance/performance.json`) until the artifact expires,
whether or not its branch still exists.

| Run | Branch, commit | What it measured | Hard disk: power-on / kernel to login | SSD: power-on / kernel to login |
|---|---|---|---|---|
| 33 | `-perf`, e1d3762 | Before any tuning | 126 s / 36.4 s¹ | 16.9 s / 5.8 s¹ |
| 34 | `-perf2`, c24bf2b | Smaller initramfs, no boot menu wait | 72.9 s / not recorded | 8.8 s / 5.0 s |
| 36 | `-perf3`, 5642445 | Plus unused services off, exam browser pre-warm | 72.9 s / 30.5 s | 8.8 s / 4.4 s |
| 44 | working branch, debe563 | The code of v1.0.0-rc1 (full release run) | 72.9 s / 31.9 s | 8.9 s / 5.0 s |
| 46 | `-perf4`, 2ced8a5 | Lab Mode's boot reset starts fewer programs; journal capped | 73.2 s / 28.2 s | 8.8 s / 4.3 s |
| 47 | working branch, 1c07b57 | Plus: the login screen doesn't wait for the network; the wipe's two parts at the same time. **Five boots per profile** | median 69.1 s / 28.8 s, worst 69.7 s / 29.8 s | median 8.9 s / 4.5 s, worst 8.9 s / 4.5 s |
| 50 | working branch, 1dbb334 | The same boot path, in a full release run (281 of 281 checks). Five boots per profile | median 69.3 s / 29.0 s, worst 72.9 s / 30.8 s | median 8.8 s / 4.5 s, worst 8.9 s / 4.6 s |

Runs 33 to 46 booted each profile once; one boot can be a second or two
either way (runs 36 and 44 booted the same boot path: 30.5 and 31.9 s).

Where the sign-in time goes now (seconds after the session opens, run 47):

| Step | Hard disk | SSD |
|---|---|---|
| Exam session started | 0.32 | 0.29 |
| Exam browser window open | 1.25 | 0.69 |
| Exam server answered | 1.52 | 0.83 |
| Exam page shown | **1.66** | **0.85** |

Memory at the idle lab desktop (452 MB in use on the hard disk profile, of
1968 MB): the largest processes are Xorg (86 MB), the Lab Mode sign-in
notice (61 MB, until the student closes it), the Bluetooth, network and
sound tray icons (52, 48, 44 MB), the file manager / desktop (43 MB) and
the update checker (24 MB).

## What was fixed

| Fix | Effect |
|---|---|
| The initramfs carried AMD/NVIDIA graphics and data-centre network drivers and firmware (179 MB) that the boot loader reads before the kernel starts. A hook (`/etc/initramfs-tools/hooks/primers-trim`) leaves them out; they load from the system a few seconds later. Every disk, USB, keyboard and Intel graphics driver stays; the build checks both. | 179 → 82 MB; ISO 2.09 → 1.90 GB; power-on on the hard disk 126 → 73 s |
| No boot menu wait (it was 5 s on every boot). Shown for 10 s when another system is installed (Ubuntu's os-prober script) or with Shift/Esc; 10 s after an interrupted boot (was 30). The installer's settings match. | −5 s on every boot |
| Services a lab PC doesn't use are no longer started at boot (packages kept; D-Bus starts blueman's and Avahi's helpers if anything asks): winbind, networkd-dispatcher, avahi-daemon, blueman-mechanism (22 s on the hard disk, in the way of the login screen), Ubuntu Pro units, apport. The fleet agent no longer starts the wait-for-network at every boot. | kernel to login 36 → 30 s (hard disk), 5.8 → 4.4 s (SSD) |
| While an exam is on, the exam browser (its programs, libraries, Python bindings; ~220 MB of cache the kernel drops when memory is needed) is read into memory after the login screen is up and after `primers-exam start`, at the lowest CPU and disk priority (`primers-exam-prewarm.service`; 9.6 s on the hard disk, 2.7 s on the SSD). | sign-in to exam page 7.2 → 1.7 s on the hard disk |
| Lab Mode's boot reset starts no programs it has nothing for: no `systemctl stop user@UID` when nothing of the lab account is running (always so at boot), no `groupadd` and `usermod` when passwordless sign-in was granted at an earlier boot, and the Exam Mode code is only loaded when an exam is on. The journal is capped at 200 MB on disk (`SystemMaxUse`, 16 MB files), so writing it to disk at boot has a bounded amount to do; the exam log keeps its own durable copy (ADR 0004). | run 46: kernel to login 31.9 → 28.2 s (hard disk, one boot) |
| **The login screen no longer waits for the network.** The vendor's `systemd-user-sessions.service` (which the login screen waits for) is replaced by a copy without `After=network.target` (the build stops if the vendor file changes). NetworkManager now starts beside the boot reset instead of before it. To keep Exam Mode's network lock first, `primers-exam-firewall.service` puts the exam firewall in place **before `network-pre.target`**, so before NetworkManager brings up any interface; the boot reset still re-applies every lock as before. The `exam-power-cut` VM test checks both orders on each release: the firewall finished before NetworkManager started, and nothing network-related is ordered before the login screen. | the network (6–7 s on the hard disk) is off the login screen's path |
| The wipe's two parts run at the same time: the lab account's home folder is rebuilt from the template while its files elsewhere are removed (`/tmp`, `/var/tmp`, `/dev/shm`, its crontab and mail, Wi-Fi connections only it could use). The wipe still finishes before the login screen can start (`Before=systemd-user-sessions.service display-manager.service`, unchanged; ADR 0004). | the wipe: 1.9 s (run 46) → 1.5–1.7 s on the hard disk |

## Misses and the plan

**Kernel to login screen on a hard disk: median under 30 s (28.8 s in
run 47, 29.0 s in run 50); the worst of ten boots was 30.8 s.** Lab Mode's
wipe still finishes before the login screen appears in every boot. Power-on to login on the hard disk still
misses the 30 s target: **median 69.1 s, worst 69.7 s.** Where the time
goes (seconds; ranges are over the five boots):

| Step | Hard disk | SSD |
|---|---|---|
| Before the kernel starts: firmware, then the boot loader reading the kernel (15 MB) and initramfs (82 MB) | **40.3** | 4.4 |
| Kernel and initramfs, up to the system's service manager | 4.2 | 1.9 |
| Service manager start-up to the basic system (reading its unit files, devices, AppArmor profiles, filesystems, swap) | 9.2–10.6 | 0.5 |
| Lab Mode's boot reset (the wipe and the locks, before the login screen) | 10.4–11.6 | 0.3 |
| …of which Python starting from a cold disk | 4.9–6.2 | |
| …of which loading the PRIMERS modules and checking the account | 3.8–4.8 | |
| …of which the wipe itself (home and the rest at the same time) | 1.5–1.7 | 0.1 |
| The display server and login screen starting | 1.8–4.5 | 1.6 |

**1. Before the kernel: 40 s of the 69 s.** The test's hard disk counts
every small read the boot loader makes against its ~120 operations a
second, which is right for scattered reads but pessimistic for reading one
long file: a real 7200 rpm disk reads 100 MB in about a second. The figure
for a real hard disk is therefore not known from this test; the pilot
measures it (the install checklist's stopwatch line, and `benchmark` in
the Brain).

- Measure on real lab PCs with hard disks: `benchmark` in the Brain
  reports boot to login from the boot's own record (on UEFI PCs including
  the firmware and boot loader; pilot guide, "Collect proof points"), and a
  stopwatch from the power button to the login screen gives the rest.
- If real PCs are slow here too: make the initramfs much smaller on
  installed PCs by building it for the PC's own hardware (`MODULES=dep`) at
  install time; expected ~25-35 MB. Needs an ADR and tests on real
  hardware first: an initramfs built for one PC may not boot if its disk is
  moved to a different PC.

**2. Lab Mode's boot reset: 10.4–11.6 s, ordered before the login screen
on purpose** (a power cut must not leave one student's files for the next:
ADR 0004). It is not moved after the login screen or into the background.
Python's own start-up is left as it is. One option left that keeps the
wipe before the login screen: start the reset as soon as the filesystems
are mounted instead of after the basic system (which takes 9–11 s on this
test's hard disk, so part of it could overlap); it would then run before
AppArmor and the temporary-file setup, so it needs its own review and tests
before it is done.

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
