# Lab pilot guide

How to run a PRIMERS OS pilot in one computer lab (the first step of the
rollout plan: one lab, Lab Mode, then Exam Mode and Primers ID) and collect
the proof points the plan asks for.

> **Pilot kit:** [docs/pilot/](pilot/README.md) has the printable pieces:
> the invigilator card, the install checklist (one per PC), the results
> sheet, the feedback forms and the rollback plan. Back up every PC first
> ([rollback plan](pilot/rollback-plan.md)).

## 1. Install

On each PC:

1. Write the ISO to a USB stick (balenaEtcher, Rufus in DD mode, or `dd`).
2. Boot from it (Secure Boot can stay on; legacy BIOS PCs work too) and
   double-click **Install PRIMERS OS**. On the Partitions page choose
   **Erase disk**.
3. Create the **staff (administrator) account** in the installer, with a
   login name such as `labadmin` (the installer refuses names the system
   already uses, such as `staff` or `lab`). Students never get this
   password.
4. When the installer restarts the PC, remove the USB stick and press Enter.

PCs with 2 GB of RAM are the target minimum; 4 GB is smooth.

### Lock the firmware (required for exams)

The operating system can't protect a PC whose firmware lets anyone boot
something else. On every lab PC, in the BIOS/UEFI setup:

- set a **firmware (supervisor) password**, kept by the lab administrator;
- turn **booting from USB, CD/DVD and the network off**, and put the
  internal disk first in the boot order;
- keep **Secure Boot on**;
- if the case can be opened, fit a lock or a tamper seal: clearing the
  firmware password usually needs access to the motherboard.

Do this after installing PRIMERS OS (installing needs USB boot).

### Privacy: name who is responsible (required)

PRIMERS OS keeps an exam log and, on paired PCs, a lab control log. Under
the Nigeria Data Protection Act 2023 the institution is responsible for
them, and the privacy notice people see must say who to contact. On every
lab PC:

```bash
sudo primers-privacy controller --name "Veritas University" --contact "dpo@veritas.example" --dpo "Name of the DPO"
primers-privacy status
```

The logs keep records for **90 days**, then a daily job deletes older
ones (never during an exam). If the institution's exam appeals take longer,
agree a time with its data protection officer and set it:
`sudo primers-privacy retention --days 180`. Everyone sees the notice the
first time they sign in to the desktop (lab students see a short version
at every sign-in, and candidates see a line in the exam's bar); it is
always under right-click › System › Privacy notice. Details:
[privacy.md](privacy.md).

For an exam appeal or someone asking for their data:
`sudo primers-exam log --export /media/usb/appeal-42` (the last exam; add
`--all` or `--since 2026-11-24`) or `sudo primers-privacy export DIR` (both
logs). Each export has checksums (`sha256sum -c SHA256SUMS`). Exports and
the invigilator's collected logs are personal data: keep them safe and
delete them when they are no longer needed.

## 2. Turn on Lab Mode

Sign in with the staff account, open a terminal and run:

```bash
sudo primers-lab enable
```

Then **restart the PC**. After the restart the login screen offers
*Shared lab account (files are deleted at sign-out)*: students click
**Log In**, no password. Everything they save is deleted when they sign
out, when the next person signs in, and at every boot.

**Same desktop on every PC (optional):** before enabling, prepare the
template the lab account is copied from:

```bash
sudo mkdir -p /etc/primers
sudo cp -a /etc/skel /etc/primers/lab-skel
```

Add bookmarks, shortcuts or a wallpaper under `/etc/primers/lab-skel`
(it must stay owned by root), then run `sudo primers-lab enable`.

Check any time:

```bash
primers-lab status
```

## 3. Run an exam (Exam Mode)

Exam Mode needs Lab Mode.

**First, find every server the exam site uses** (once per exam site, on any
PRIMERS PC, signed in as staff, not with sudo):

```bash
primers-exam probe https://cbt.example.edu.ng
```

A window opens on the exam site. Sign in with a test account and go through
a practice exam (sign-in, instructions, questions, review, submit), then
press **Done**. The probe lists every server the site loaded from, checks
each one answers from this PC (IPv4 and IPv6) and prints the exact command
to start the exam, for example:

```bash
sudo primers-exam start https://cbt.example.edu.ng/login/index.php --allow cdn.jsdelivr.net
```

Moodle, for one, loads its maths display (MathJax) from `cdn.jsdelivr.net`
on every quiz page; without that `--allow` the quiz still opens but the
maths doesn't. A server on a port other than 80/443 is given as
`--allow host.name:8443`. If the probe says a server can't be found or
didn't answer, fix that before the exam: it won't work for candidates
either.

Then, before the exam, on each PC, as staff, run the probe's command.
Servers whose addresses change during the exam (CDNs) are followed every
five minutes; you don't need to do anything. Start the exam with nobody
signed in to the PC's desktop (or sign out afterwards): the login screen
then restarts with the consoles locked. While an exam runs, candidates can't
switch to text consoles, use Magic SysRq keys, open a terminal, run sudo,
su or pkexec, change the clock, look up any name but the exam servers', take
screenshots, use USB drives, or get out of the exam page. On an installed PC
the boot menu is locked too: editing it, recovery mode and other systems need
a password nobody has (stop the exam to unlock it). Then try it: sign in to the lab
account and check the exam loads. Candidates see only the exam, full
screen; they press **Finish exam** when done, which signs them out and wipes
the account. After the exam:

```bash
sudo primers-exam log      # sessions, pages, blocked attempts, finishes
sudo primers-exam stop
```

**If the power goes off** (or a candidate restarts the PC), the PC comes
back to the login screen with the exam still on and every lock in place;
the candidate signs in again and carries on. The exam log keeps everything
up to the moment of the cut (`sudo primers-exam log` shows the exam that is
running, or the last one; `--all` shows every exam). This needs an
installed PC: a live USB forgets everything when it restarts.

### Run the whole lab from the invigilator's PC (primers-fleet)

Instead of going to every PC, the invigilator can start, watch and stop the
exam on all of them from one PRIMERS PC (a staff laptop or desk PC, never a
lab PC: it holds the key that controls the lab).

**Pair once** (per lab, before the first exam). On the invigilator's PC:

```bash
sudo primers-fleet pair
```

It shows a one-time code and the command to type on each lab PC, e.g.:

```bash
sudo primers-fleet join 192.168.1.10 4KQ7-M2XD-9PTA
```

Each PC appears on the invigilator's screen as it joins; press Ctrl+C when
all have. Only PCs that typed the code are paired; the code is useless once
pairing ends. Each lab PC then accepts commands from that invigilator PC
only (its firewall lets only that address in).

**On exam day**, on the invigilator's PC:

```bash
sudo primers-fleet status --watch 10      # every PC: reachable, Lab Mode, exam, candidate, last event
sudo primers-fleet exam-start https://cbt.example.edu.ng/login/index.php --allow cdn.jsdelivr.net
sudo primers-fleet exam-stop
sudo primers-fleet collect ~/exam-logs     # every PC's exam log, with SHA256SUMS
```

`--pc lab-07` limits a command to some PCs. Lab Mode must already be on
on each lab PC. Every command is recorded on both sides in
`/var/log/primers/fleet.jsonl`. To unpair: `sudo primers-fleet forget NAME`
on the invigilator's PC, `sudo primers-fleet leave` on the lab PC.

## 4. Study Mode for students

Any student can type `study 25` in the PRIMERS Brain (or right-click the
desktop › Study Mode). Primers Lite Bee then pauses social media, video,
games and betting sites for 25 minutes and the panel counts down.

### Less movement on screen

For anyone who finds movement on screen distracting or uncomfortable:

```bash
sudo primers-reduce-motion on      # or: off, status
```

The boot splash's blinking cursor stays still (from the next boot), and
windows and web pages stop animating (pages see the browser's "reduce
motion" setting).

## 5. Sign in with Primers ID

> The live Primers ID service isn't running yet: until it is,
> `primers-id login` says it can't be reached. Details:
> [primers-id.md](primers-id.md).

In a terminal (right-click the desktop › Terminal), each person types:

```bash
primers-id login
```

It asks for a PIN for days without internet (4 or more digits; Enter to
skip), then shows an address and a code. Open the address on the PC or a
phone, sign in to Primers ID there and approve the code: PRIMERS OS never
asks for the Primers password itself. When the internet is down,
`primers-id login --offline` takes the PIN instead, for 14 days after the
last online sign-in (five wrong PINs lock it until the next online
sign-in). `primers-id status` shows who is signed in; `primers-id logout`
signs out. On Lab Mode PCs the sign-in is wiped with the lab account after
every session, but ask students to sign out anyway.

To use a campus provider, or the real Primers ID service once it is live,
edit `/etc/primers/id.conf` (issuer and client ID): nothing else changes.

## 6. Collect proof points

The plan asks for boot time and RAM use on real lab hardware. On each PC:

1. Shut it down completely, then switch it on (a cold boot).
2. Sign in with the **staff** account (lab-account files are wiped, so the
   report would be lost) and wait two minutes so the system is idle.
3. Open the PRIMERS Brain and type `benchmark`.

It shows boot-to-login time, RAM installed and in use, disk type and size
against the PRIMERS targets (2 GB RAM; under 600 MB idle; under 15 s on an
SSD or 30 s on a hard disk; under 8 GB installed) and saves a JSON report in
`~/.local/share/primers/benchmarks/`. Copy those files to a USB stick. They
contain hardware facts and timings only, no names or files.

Also time a cold boot with a stopwatch, from pressing the power button to
the login screen, and write it down with the PC's disk type (hard disk or
SSD): the virtual-machine figures in `docs/benchmarks.md` (also in
`/usr/share/doc/primers/` on every PC) can't tell how a real hard disk
does.

Also record, per lab: how many PCs were revived (couldn't run Windows 11),
licence cost saved per seat, and a short student satisfaction survey.

Send these figures to Primers: they go into section 7.10 of the knowledge
base (`docs/knowledge/PRIMERS_KNOWLEDGE.md`), which Ask Primers answers from
on every PC (try `ask how fast does it boot on a hard disk?` in the PRIMERS Brain).

## 7. If something goes wrong

| Problem | What to do |
|---|---|
| The lab account isn't on the login screen | Restart the PC once after `primers-lab enable`. |
| Clicking the lab account returns to the login screen | Lab Mode refused to start a session it couldn't wipe. See why: `journalctl -t primers-lab`. |
| Part of the exam page is missing or broken (maths, images, fonts) | The site uses a server that isn't allowed. `sudo primers-exam log` lists what was blocked; run `primers-exam probe` again, going through every kind of exam page, and restart the exam with its command. |
| TCExam's sign-in keeps returning to the login page | TCExam marks its cookies Secure by default, which browsers drop on plain `http`. Serve TCExam over `https`, or set `K_COOKIE_SECURE` to `false` in TCExam's `shared/config/tce_config.php`. |
| `primers-fleet status` shows a PC as unreachable | Check it is on and on the network. If the invigilator PC's or the lab PC's address changed, run `sudo primers-fleet pair` again and `sudo primers-fleet join ...` on that PC. |
| `primers-fleet join` says the other PC doesn't know the code | Check the code and the invigilator PC's address; pairing must still be open (`primers-fleet pair` running there). |
| A student lost work | Expected in Lab Mode. Remind students to save to USB or online; the sign-in notice says so. |
| The exam page doesn't load | `primers-exam status` (firewall active?). If the site needs other servers, stop and start again with `--allow` for each. `sudo primers-exam log` shows blocked pages. |
| The power went off during an exam | Switch the PC back on and let the candidate sign in again. `sudo primers-exam status` should say Exam Mode: ON with every line locked or active. |
| "Boot menu: NOT LOCKED" in `primers-exam status` | Run `sudo primers-exam stop`, then start the exam again; if it stays unlocked, check `sudo update-grub` works. |
| Turn Lab Mode off | `sudo primers-lab disable` (deletes the lab account). |
