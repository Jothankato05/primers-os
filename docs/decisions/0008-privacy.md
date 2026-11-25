# 0008 — Privacy: the notice, log retention and export (NDPA 2023)

- **Status:** accepted
- **Date:** 2026-11-25
- **Builds on:** [0002](0002-exam-mode-lockdown.md), [0004](0004-exam-power-cuts.md) (the exam log),
  [0006](0006-fleet-control.md) (the lab control log), [0007](0007-primers-id.md)

## Context

PRIMERS OS records personal data on campus PCs: the exam log (which
account signed in, the exam pages opened, blocked attempts, times), the
lab control log (commands and network addresses) and the system journal
(sign-in times, and a copy of the exam events). Until now these were kept
forever and nobody was told about them.

The Nigeria Data Protection Act 2023 (NDPA) requires people to be told,
when their data is collected, who is responsible, what is collected and
why, the lawful basis, how long it is kept, who receives it and their
rights (access, correction, deletion, restriction, objection, portability,
withdrawing consent, complaining to the Nigeria Data Protection
Commission). Data may be kept no longer than needed, and a person may ask
for a copy. Students may be under 18. The institution running the lab, not
Primers, is the data controller: PRIMERS OS sends nothing it records to
Primers.

Hard to undo: deleting records can't be reversed, and a retention time
shorter than an institution's appeal window would destroy evidence.

## Decisions

| Concern | Decision | Test |
|---|---|---|
| Who is responsible | `/etc/primers/privacy.conf` names the institution, its contact and its data protection officer (`sudo primers-privacy controller`). Until they are set the notice says so ("ask the lab administrator") rather than inventing a contact. | unit |
| The notice | One text (`core/privacy.py`, versioned), covering what the NDPA asks for, with this PC's institution and retention times filled in. The same text is in `docs/privacy.md` (a unit test keeps them identical). Not legal advice: the institution's DPO confirms the lawful basis. | unit (each required element), VM |
| When it is shown | Installed PCs: the first desktop sign-in of each account, until the person ticks "I have read this privacy notice" and presses OK (OK stays disabled until then; "Later" shows it again next time); again for everyone when its version changes. Any time: System › Privacy notice, `privacy` in the PRIMERS Brain, `primers-privacy notice --text`. | unit (fake zenity: Later, OK, not again, a new version), VM (real window, keyboard, next sign-in, the menu) |
| The shared lab account | Its home is wiped after every session, so the full window would come back at every sign-in. Instead the shared-computer notice it already shows carries a short layer (what is recorded, for how long, where the full notice is): a layered notice. | unit, VM |
| Exam candidates | The exam kiosk's bar shows "This exam is logged: exam pages opened, pages blocked, sign-in and finish times." whenever no other message is shown (the kiosk can't show a dialog). | kiosk self-test (CI) |
| The live USB | Doesn't open the notice at sign-in (it is for trying and installing, and a dialog over the installer would get in the way); the menu item works. | unit |
| Retention | Exam log and lab control log: 90 days by default, each configurable from 1 to 3650 days (`sudo primers-privacy retention`). A daily timer (`OnCalendar=daily`, `Persistent=true`, 15 minutes after boot) removes older records. Never from the exam log while an exam is running: the next run catches up. | unit, VM |
| Rewriting a log safely | The retention pass writes the remaining records to a new file (same owner and mode), fsyncs it and renames it over the log, so a power cut leaves the old or the new log. Every writer of these logs (Exam Mode, its log writer, primers-fleet) and the retention pass hold one lock (`<log>.lock`): a separate file, because the log itself is replaced. A line torn by a power cut goes with the record before it. Symlinks are refused. | unit (200 appends during repeated pruning, none lost; torn lines; modes; symlink) |
| The journal | It holds a copy of the exam events, so a journald drop-in limits it to the exam log's retention (`MaxRetentionSec`) and starts a new file weekly (`MaxFileSec=7day`), so entries outlive the limit by at most a week. Changing the retention rewrites the drop-in and restarts journald. | unit, VM |
| Export | `sudo primers-privacy export DIR` (and `sudo primers-exam log --export DIR` for the exam log as `log` shows it) writes a new folder, readable only by whoever ran sudo: each log as JSON lines and CSV, `README.txt`, `SHA256SUMS`. CSV cells that a spreadsheet would run as a formula are prefixed with `'`. It never writes into an existing folder. | unit, VM (`sha256sum -c`) |
| Nothing phones home | Firefox: telemetry and studies off by enterprise policy. Ubuntu's motd news, Ubuntu Pro's timer and apport's report timer are disabled; whoopsie and popularity-contest must not be installed. The image build fails if any of this changes, because the notice promises it. | build checks, VM |

## Limits we accept

- **Deleting one person's records on request** isn't a command: the exam
  log is one file per PC shared by every candidate of an exam, and removing
  one person's lines would weaken the evidence for all of them. The
  institution decides with its DPO; the retention time can be shortened
  for everyone.
- **Copies outside the PC** (the invigilator's `primers-fleet collect`
  folder, exports) aren't covered by the retention timer; the notice and
  the export's README say they are the institution's to protect and delete.
- **The shared lab account's identity** is the account, not the person;
  matching an exam log to a candidate uses the exam's own seating records.
- **The live USB** records the same logs while it runs, but they disappear
  at shutdown (nothing persists).

## Alternatives not taken

- **Showing the full notice at every lab sign-in:** students would click
  through it dozens of times a week; a layered notice tells them at each
  sign-in and keeps the full text one click away.
- **A notice on the login screen:** the greeter has no room for it, and it
  would be shown to nobody in particular.
- **Pruning by rotating files (logrotate):** works on whole files, not
  record times, and splits one exam across files.
- **Unlimited retention, or "forever" as an option:** contrary to the
  NDPA's storage limitation; 3650 days is the ceiling.
- **Encrypting the logs on disk:** root and the `adm` group must read them
  anyway, and full-disk encryption is the right layer for stolen PCs.

## Rollback

`sudo systemctl disable --now primers-privacy-retention.timer` stops the
deletion; removing `/etc/systemd/journald.conf.d/90-primers-retention.conf`
returns the journal to Ubuntu's defaults. Deleted records can't be brought
back: export first (`sudo primers-privacy export DIR`) before shortening the
retention time.
