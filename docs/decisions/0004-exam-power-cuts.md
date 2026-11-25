# 0004 — Exam Mode across power cuts and reboots

- **Status:** accepted
- **Date:** 2026-11-25
- **Builds on:** [0002](0002-exam-mode-lockdown.md), [0003](0003-exam-escape-hardening.md)

## Context

Power cuts are common where PRIMERS OS is used, and a candidate can also
reboot a PC on purpose. After either, an exam PC must come back **in Exam
Mode** (never unlocked, never a desktop), and the exam log must still hold
everything that happened before the cut. Three gaps were found:

1. Exam Mode's files were written without `fsync` and `exam.conf` was
   written last, so a cut just after `primers-exam start` could come back
   with some locks and no exam (not in Exam Mode). Stopping removed
   `exam.conf` first, so a cut during `stop` left locks that `stop` no
   longer knew about.
2. The exam log was the journal only. journald writes to disk every five
   minutes by default (`SyncIntervalSec=5m`), so a cut could lose the last
   minutes of an exam, exactly the part that matters in a dispute.
3. A reboot passes through the boot menu, where anyone can edit the kernel
   command line (`init=/bin/sh` is a root shell), pick recovery mode, or
   boot another system on the disk.

## Decisions

| Gap | Decision | Test |
|---|---|---|
| Lock state | Every Exam Mode and Lab Mode file is written to a temporary file, fsync'd, renamed over the old one and its directory fsync'd. `exam.conf` is written **before** the locks and removed **after** them; `start` and `stop` end with a `sync`. A cut at any point leaves either no exam or an exam that the boot service locks again (and that `stop` can stop). | unit (a simulated cut inside `start` and inside `stop`, then the boot refresh) |
| Back on | Unchanged from 0002/0003 and now tested after a real cut: the Lab Mode boot service (ordered before the display manager) re-applies the firewall and every lock, and each exam sign-in does it again and refuses the session if it can't. | VM (power cut) |
| Exam log | `/var/log/primers/exam.jsonl`, one JSON line per event, appended with `O_APPEND` and fsync'd before the call returns. Root's events (start, stop, refresh, failures) are written by the process that logs them. The candidate's events (session, pages, blocked attempts, finish) come from the lab account through syslog; the `primers-exam-log` service follows the journal and copies each one as soon as journald has it. A line torn by a cut is skipped when reading, and the next append starts a new line. The journal still gets everything too. | unit, VM (an event one second before the cut is in the log after it) |
| Boot menu | While an exam runs on an installed system, `primers-exam` writes `/etc/grub.d/09_primers_exam` and `/etc/default/grub.d/90-primers-exam.cfg` and runs `update-grub`: a GRUB superuser with a random password that is thrown away, the normal entry from `10_linux` repeated first with `--unrestricted`, recovery entries and other systems (os-prober) off. The PC boots on its own; editing an entry, the GRUB command line and every other entry ask for a password nobody has. `stop` removes both files and runs `update-grub`. The live USB's menu is on the USB stick and can't be locked (`status` says so: exams need installed PCs). | unit (the real script against a 10_linux sample, `grub-script-check`), VM (pressing `e` after the cut asks for a password; the PC then boots normally) |

## Alternatives not taken

- **Editing `/etc/grub.d/10_linux`** to add `--unrestricted`: it is a
  package conffile, so upgrades would conflict with or undo the edit.
  Re-emitting its first entry from our own script reads `10_linux` as it
  is; the image build fails if `10_linux` stops looking the way the script
  expects, and `primers-exam start` fails (and rolls back) if the lock
  doesn't end up in `grub.cfg`.
- **A known GRUB password for staff:** one more secret to manage on every
  PC. Staff who need the menu stop the exam first.
- **Making journald sync every message** (`SyncIntervalSec=0` is not
  per-message, and syncing everything costs every program on the PC);
  copying only the exam's own entries to a small file is cheaper and
  stronger.

## Consequences

- An installed exam PC that loses power comes back to the login screen
  with the exam on; candidates sign in again and continue. The firmware
  must still be locked (pilot guide): the OS can't stop a USB boot.
- The exam log survives a cut up to the last second or so before it. It
  is root's (group `adm` can read it); the retention and export rules
  come with the privacy work (sprint task 9).
- `update-grub` runs at `start` and `stop` (a few seconds), not at every
  sign-in: refreshing only rewrites the lock when it is missing.
- Rollback: `primers-exam stop` undoes all of it; an image without this
  change ignores the files (and the build removes them from the image).
