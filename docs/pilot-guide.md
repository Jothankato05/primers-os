# Lab pilot guide

How to run a PRIMERS OS pilot in one computer lab (the first step of the
rollout plan: one lab, Lab Mode, then Exam Mode and Primers ID) and collect
the proof points the plan asks for.

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

Exam Mode needs Lab Mode. Before the exam, on each PC, as staff:

```bash
sudo primers-exam start https://cbt.example.edu.ng
```

If the exam site loads anything from another server (a CDN, a login
server), add each with `--allow host.name`. Start the exam with nobody
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

## 4. Study Mode for students

Any student can type `study 25` in the PRIMERS Brain (or right-click the
desktop › Study Mode). Primers Lite Bee then pauses social media, video,
games and betting sites for 25 minutes and the panel counts down.

## 5. Collect proof points

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

Also record, per lab: how many PCs were revived (couldn't run Windows 11),
licence cost saved per seat, and a short student satisfaction survey.

## 6. If something goes wrong

| Problem | What to do |
|---|---|
| The lab account isn't on the login screen | Restart the PC once after `primers-lab enable`. |
| Clicking the lab account returns to the login screen | Lab Mode refused to start a session it couldn't wipe. See why: `journalctl -t primers-lab`. |
| A student lost work | Expected in Lab Mode. Remind students to save to USB or online; the sign-in notice says so. |
| The exam page doesn't load | `primers-exam status` (firewall active?). If the site needs other servers, stop and start again with `--allow` for each. `sudo primers-exam log` shows blocked pages. |
| The power went off during an exam | Switch the PC back on and let the candidate sign in again. `sudo primers-exam status` should say Exam Mode: ON with every line locked or active. |
| "Boot menu: NOT LOCKED" in `primers-exam status` | Run `sudo primers-exam stop`, then start the exam again; if it stays unlocked, check `sudo update-grub` works. |
| Turn Lab Mode off | `sudo primers-lab disable` (deletes the lab account). |
