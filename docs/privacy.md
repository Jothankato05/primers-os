# Privacy on PRIMERS OS

What PRIMERS OS records, for how long, and how an institution meets the
Nigeria Data Protection Act 2023 (NDPA) with it. Decisions:
[ADR 0008](decisions/0008-privacy.md).

> This page and the notice are written to follow the NDPA's transparency
> rules. They are not legal advice: the institution running the PCs should
> have its data protection officer or lawyer confirm the lawful basis and
> the retention times before a pilot.

## The notice people see

- **First sign-in:** on an installed PC, the first time each account signs
  in to the desktop, the notice opens in a window. It stays until the
  person ticks "I have read this privacy notice" and presses OK ("Later"
  shows it again at the next sign-in). It is shown again to everyone when
  the notice changes (a new version).
- **Any time:** right-click the desktop › System › Privacy notice, or type
  `privacy` in the PRIMERS Brain, or run `primers-privacy notice --text`.
- **The shared lab account (Lab Mode):** its files are wiped after every
  session, so the shared-computer notice it shows at every sign-in carries
  a short version (what is recorded, for how long, where the full notice
  is) instead of the full window every time.
- **Exam candidates:** the exam kiosk's bar says "This exam is logged: exam
  pages opened, pages blocked, sign-in and finish times." whenever it
  isn't showing another message.
- **The live USB** doesn't open it at sign-in (it is for trying and
  installing); the menu item works there too.

The notice as shipped (the institution's details are filled in with
`sudo primers-privacy controller`, the days with
`sudo primers-privacy retention`):

```text
PRIMERS OS PRIVACY NOTICE
Version 2026-11-25

This notice explains what PRIMERS OS records on this computer, why, for
how long, who can see it, and your rights under the Nigeria Data
Protection Act 2023 (NDPA).

WHO IS RESPONSIBLE
The institution that runs this computer decides how it is used and is
responsible (the data controller) for what is recorded on it:
  Institution: Not set on this computer: ask the lab administrator.
  Contact: ask the lab administrator
  Data protection officer: ask the lab administrator
PRIMERS OS is made by Primers Group (primersgroup.ng). PRIMERS OS does not
send anything it records on this computer to Primers.

WHAT IS RECORDED, AND WHY
1. Exam log, only while an exam is running in Exam Mode: when the exam
   started and stopped, which account signed in and when, the addresses of
   the exam pages that were opened, pages and connections that were
   blocked, and when the candidate finished. Why: to run exams fairly and
   to settle questions about what happened during one. Lawful basis: the
   institution's task of running and supervising exams (public interest or
   legitimate interests; the institution confirms which). Kept for 90
   days, then deleted automatically.
2. Lab control log, only on PCs linked to an invigilator's PC (primers-
   fleet): which PC sent which command (start, stop, status, collecting
   the exam logs), from which network address, and when. Why: security,
   and to show who controlled an exam. Kept for 90 days.
3. The system's technical log (the journal), which also holds the exam
   events and sign-in times: kept for at most 90 days (up to 7 more while
   its current file is in use).
4. On the shared lab account (Lab Mode), everything saved in the
   account, browser history included, is deleted at every sign-in, sign-
   out and restart.
5. Primers ID, only if you sign in with it (primers-id): your Primers
   ID number, name, email and a sign-in token, kept in your own account
   folder (readable by you only) until you sign out. The Primers ID
   service itself is run by Primers Group under its own privacy notice.
6. Your own files and settings stay in your account folder.

WHAT IS NOT RECORDED
No keystrokes, screenshots, screen recordings, camera or microphone, and
not the answers you give in an exam (they go to the exam site, which your
institution runs). No advertising and no usage tracking: Firefox's
telemetry is turned off.

WHO CAN SEE IT
The exam and lab control logs: this computer's administrators, and the
invigilator, who may copy every lab PC's exam log at the end of an exam.
The institution shares them outside itself only when the law requires it.

CONNECTIONS TO THE INTERNET
Software updates come from Ubuntu's servers, which see this computer's
network address. Websites you visit see what any website sees. During an
exam only the exam site can be reached.

YOUR RIGHTS
Under the NDPA you can ask the institution (contact above) to tell you
what it holds about you and give you a copy, to correct it, to delete it,
to restrict or object to its use, to give it to you in a portable form,
and to stop using it where you consented. You can complain to the Nigeria
Data Protection Commission (NDPC, ndpc.gov.ng). For a student under 18, a
parent or guardian can act for them.

FOR ADMINISTRATORS
sudo primers-privacy export DIR copies the logs (JSON and CSV, with
checksums) for a request; sudo primers-privacy retention --days N changes
how long they are kept; sudo primers-privacy controller sets the contact
details above. Full text: /usr/share/doc/primers/privacy.md.
```

## What is kept, and where

| Record | Where | Kept | Who can read it |
|---|---|---|---|
| Exam log | `/var/log/primers/exam.jsonl` | 90 days (`exam_log_days`) | root and the `adm` group; the invigilator collects copies |
| Lab control log (primers-fleet) | `/var/log/primers/fleet.jsonl` | 90 days (`fleet_log_days`) | root and the `adm` group |
| System journal (also has the exam events) | `/var/log/journal` (installed PCs) | the exam log's days, plus up to 7 days | root and the `adm` group |
| Lab account's files | `/home/lab` | until the session ends | the session |
| Primers ID sign-in | `~/.local/share/primers/id` | until `primers-id logout` | the person |
| Benchmark reports | `~/.local/share/primers/benchmarks` | until deleted | the person |

A daily timer (`primers-privacy-retention.timer`, 15 minutes after boot and
then daily, catching up after the PC was off) removes records older than
the retention time. It never touches the exam log while an exam is running:
the next run after the exam catches up. Copies made with
`primers-fleet collect` or an export are the institution's to keep safe
and delete.

Nothing is sent to Primers. Firefox's telemetry and studies are turned off
by policy; Ubuntu's message-of-the-day news, Ubuntu Pro's timer and
automatic crash reports are off; no crash-upload or popularity-contest
software is installed (the image build checks all of this).

## For administrators

```bash
sudo primers-privacy controller --name "Veritas University" --contact "dpo@veritas.example" --dpo "Name"
sudo primers-privacy retention --days 90        # the exam log (and the journal); --fleet-days N for the lab control log
primers-privacy status                          # what is kept, the oldest record, the settings
sudo primers-privacy export /media/usb/request-42 [--since 2026-11-01] [--exam-only]
sudo primers-exam log --export DIR              # the last exam only (or --since / --all), the same files
```

An export is a new folder (readable only by the person who ran `sudo`)
with each log as JSON lines and as CSV (cells a spreadsheet would run as a
formula are prefixed with `'`), a `README.txt` and `SHA256SUMS`
(`sha256sum -c SHA256SUMS` checks the copy). Use it to answer a person's
request for their data, for an exam appeal, or for an auditor.

Retention can be 1 to 3650 days. Settings are in
`/etc/primers/privacy.conf`; changing them by hand takes effect at the next
daily run (`sudo primers-privacy prune` applies them now).

## For an access, correction or deletion request

1. Confirm who is asking. Exam logs name the account (the shared lab
   account on lab PCs), so match times and seats with the exam's own
   records.
2. `sudo primers-privacy export DIR --since <exam date>` on the PC (or use
   the copies the invigilator collected), and give the person what concerns
   them.
3. Deleting records before their time would remove evidence for every
   candidate in that exam; decide with the data protection officer. The
   retention time can be shortened for everyone with
   `sudo primers-privacy retention --days N`.
