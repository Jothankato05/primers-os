# Lab pilot guide

How to run a PRIMERS OS pilot in one computer lab (the first step of the
rollout plan: one lab, Lab Mode, then Exam Mode and Primers ID) and collect
the proof points the plan asks for.

## 1. Install

On each PC:

1. Write the ISO to a USB stick (balenaEtcher, Rufus in DD mode, or `dd`).
2. Boot from it (Secure Boot can stay on) and double-click **Install PRIMERS OS**.
3. Create the **staff (administrator) account** in the installer. Students
   never get this password.
4. When the installer restarts the PC, remove the USB stick and press Enter.

PCs with 2 GB of RAM are the target minimum; 4 GB is smooth.

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

## 3. Study Mode for students

Any student can type `study 25` in the PRIMERS Brain (or right-click the
desktop › Study Mode). Primers Lite Bee then pauses social media, video,
games and betting sites for 25 minutes and the panel counts down.

## 4. Collect proof points

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

## 5. If something goes wrong

| Problem | What to do |
|---|---|
| The lab account isn't on the login screen | Restart the PC once after `primers-lab enable`. |
| Clicking the lab account returns to the login screen | Lab Mode refused to start a session it couldn't wipe. See why: `journalctl -t primers-lab`. |
| A student lost work | Expected in Lab Mode. Remind students to save to USB or online; the sign-in notice says so. |
| Turn Lab Mode off | `sudo primers-lab disable` (deletes the lab account). |
