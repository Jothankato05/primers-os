# 0005 — Real exam sites: finding their servers, servers that move, IPv6

- **Status:** accepted
- **Date:** 2026-11-25
- **Builds on:** [0002](0002-exam-mode-lockdown.md), [0003](0003-exam-escape-hardening.md)

## Context

Exam Mode lets the candidate's account reach only the exam servers on its
allow list (nftables per account, names pinned in `/etc/hosts`, every other
DNS lookup refused). Real CBT platforms broke that model in three ways:

1. **Staff can't know every server an exam site uses.** Moodle 4.5 loads
   MathJax from `cdn.jsdelivr.net` on every quiz page by default; others use
   a font CDN, a separate login server or a media server on another port. A
   missing server shows up mid-exam as a broken page.
2. **CDN addresses change.** The addresses were resolved once, at
   `start`. A CDN that moves during a three-hour exam (or between the start
   and a restart after a power cut) leaves the firewall pointing at the old
   addresses.
3. **IPv6.** A campus server reachable only over IPv6 must work, and the
   lock must hold on IPv6 as on IPv4.

## Decisions

| Problem | Decision | Test |
|---|---|---|
| Unknown servers | `primers-exam probe URL` opens the site in Lite Bee's probe window (`lite-bee --probe`): the kiosk's engine, a throw-away profile, no content blocking. Staff sign in with a test account and click through a practice exam; every page, script, style, font, frame, redirect, download and background request is recorded by host and port. The probe then resolves each host (IPv4 and IPv6), checks each port answers from this PC and prints the exact `primers-exam start ... --allow ...` command (`--json` for scripts). It runs as the person at the desktop, never as root. `--allow host:port` opens a port besides 80/443 for that server. | unit (analysis, command, CLI), CI (the probe window against a local multi-server site), VM (Moodle: finds the MathJax CDN; TCExam: needs nothing else) |
| Servers that move | `primers-exam-refresh.timer` runs `primers-exam refresh` every 5 minutes during an exam (and the lock is refreshed at boot and at every exam sign-in). It re-resolves the allowed names as root and updates the pins and the firewall. An address a server **had** stays allowed for 1 hour after it was last seen (connections already open and the browser's cached answers keep working), and at most the 16 most recent addresses per server are kept. Each move is written to the exam log ("exam server X moved: now also ..."). | unit (grace, cap, timer units), VM (the "CDN" moves to a new address mid-exam: the page keeps loading from it; the old address is still allowed during the grace; the log records the move) |
| IPv6 | The firewall table is `inet` (IPv4 and IPv6 together); AAAA addresses are pinned and allowed like A addresses. | VM (an exam server reachable only over IPv6 works; another IPv6 server, not on the list, is refused). The release workflow requires IPv6 on the test machine for this scenario. |

## Alternatives not taken

- **Allowing whole CDN ranges or wildcard names** (`*.jsdelivr.net`): a CDN
  serves everyone's content, so a range opens far more than the exam.
  Names stay exact; the probe finds them.
- **Letting the candidate's browser use DNS for allowed names only** (a
  filtering resolver): more moving parts on every PC, and DNS answers from
  the browser could still be used as a channel. Root resolves; the
  candidate's account never queries DNS.
- **No grace for old addresses:** a CDN that rotates addresses would cut
  pages that are loading at that moment. One hour, capped at 16 addresses
  per name, keeps the allow list small while covering rotation.
- **Following addresses without a cap:** a hostile or broken DNS server
  could keep handing out new addresses and widen the allow list; the cap
  bounds it.

## Consequences

- Staff run the probe once per exam site (or after the site changes) and
  copy its command to each PC. Only the pages opened in the probe are
  counted, so it says to go through every kind of page the exam uses.
- During an exam, a server's previous addresses stay reachable for up to
  an hour. They are addresses that server really had, only for the exam
  account, and only on the ports allowed.
- The refresh needs working DNS on the PC (root's resolver). If DNS is
  down, the last known addresses stay in force.
- Real platforms tested in VMs: Moodle 4.5 (a quiz from sign-in to
  submission) and TCExam 17 (sign-in to termination), each started with the
  probe's own command. TCExam marks its cookies `Secure` by default, so
  over plain `http` its sign-in loops back to the login page in any
  browser: serve it over `https`, or set `K_COOKIE_SECURE` to `false` in
  its `shared/config/tce_config.php` (pilot guide).
- Rollback: `primers-exam stop` removes the pins, the firewall table and
  `addresses.json`; the timer does nothing when no exam runs
  (`ConditionPathExists=/etc/primers/exam.conf`). Images without this
  change resolve once at `start`, as before.
