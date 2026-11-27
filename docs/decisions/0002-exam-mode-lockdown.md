# 0002 - Exam Mode: kiosk session plus a per-account firewall

- **Status:** accepted
- **Date:** 2026-11-24

## Context

The Primers knowledge base defines Exam Mode as "locked down by the
institution for computer-based tests: only the exam app, no network except
the exam server, activity logged". Nigerian universities run CBT through
web applications on a campus or hosted server, so "the exam app" is a web
site. The first pilot is one computer lab that already runs Lab Mode (a
shared `lab` account wiped before and after every session).

A browser kiosk alone is not a lockdown: anything else that runs in the
session (or a way out of the kiosk) would reach the internet. A firewall
alone doesn't stop candidates from using the desktop.

## Decision

Exam Mode is built on Lab Mode and has three independent layers:

1. **Session.** `/etc/X11/Xsession.d/98primers-exam` replaces the lab
   account's session with `/usr/lib/primers/exam-session` (Openbox with no
   key or menu bindings, and Lite Bee `--kiosk`), whichever session was
   chosen at the login screen. It runs before anything the candidate
   controls: Lab Mode rebuilds the home from a root-owned template before
   the session starts. The image ships Openbox as its only login session;
   the GNOME session stack is excluded (it came in as recommendations) and
   the build fails if another X or Wayland session appears.
2. **Browser.** Lite Bee's kiosk shows only the servers listed in
   `/etc/primers/exam.conf`: no address bar, tabs, downloads, file picker,
   printing, context menu or developer tools; new windows open in place;
   "Finish exam" ends the session.
3. **Network.** An nftables table (`inet primers_exam`) sends only packets
   from the lab account's sockets (`meta skuid`) to a chain that accepts
   loopback (DNS through systemd-resolved) and the exam servers' web ports,
   and rejects everything else. Other accounts and kernel-generated
   packets are untouched. It is a separate table, so ufw reloads (which
   flush the built-in iptables chains) don't remove it.

USB mounting is denied to the lab account through a mandatory polkit
local-authority file. Sessions, pages visited, blocked pages and finishes
go to the journal under `primers-exam`.

**Fail closed:** the firewall is re-applied at boot and before every lab
session; if it can't be, LightDM is told to refuse the session.

## Consequences

- Works with any web-based CBT system; the invigilator only needs its
  address (and any other servers it loads from, via `--allow`).
- Addresses are resolved when the exam starts, at boot and at each
  sign-in. A CBT site behind a CDN with rotating addresses may need its
  CDN host listed with `--allow`; when the servers can't be resolved at
  boot, the lab account is blocked from everything rather than opened up.
- A candidate who pulls the power cable loses the session, not the exam:
  answers live on the exam server, and Lab Mode wipes the PC at boot.
- Not covered: physical cheating, a second device, or exam apps that are
  native programs rather than web sites (they would need their own kiosk
  launcher in `exam-session`).
- Dropping the GNOME packages removed 167 packages (gdm3, gnome-shell,
  evolution-data-server, rygel, whoopsie, …) from the image.
