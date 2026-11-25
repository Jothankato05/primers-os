# 0003 — Closing the escape routes around the exam kiosk

- **Status:** accepted
- **Date:** 2026-11-24
- **Builds on:** [0002](0002-exam-mode-lockdown.md)

## Context

Exam Mode (ADR 0002) put candidates in a full-screen kiosk with a firewall
around their account. The end-to-end test was then finished from a text
console (Ctrl+Alt+F2): if the invigilator could reach one, so could a
candidate. A review of everything a candidate can touch (keyboard, browser,
clipboard, clock, name lookups, account privileges, power) found more
routes that had to be closed and proved closed by automated tests.

## Decisions

Every lock is applied by `primers-exam start`, re-applied at boot and before
every exam sign-in, and removed by `primers-exam stop`. Locks that must hold
across a power cut are files on disk, not runtime state.

| Route | Decision | Test |
|---|---|---|
| Ctrl+Alt+F1..F12, Ctrl+Alt+Backspace | `DontVTSwitch` and `DontZap` in `/etc/X11/xorg.conf.d/90-primers-exam.conf` (read by every display server started during the exam; starting an exam restarts the login screen when nobody is using the desktop) and `setxkbmap -option srvrkeys:none` inside the exam session, which covers a display started before the exam | VM |
| Text console login prompts | `getty@` and `autovt@` masked; idle ones stopped. A staff member's own console session is left alone | VM, unit |
| Magic SysRq | `kernel.sysrq = 0` (`/etc/sysctl.d/90-primers-exam.conf` and applied at once) | VM, unit |
| Automatic sign-in | `autologin-user=` for any account but `lab` is commented out (with a marker, restored at stop), so the login screen, and with it the kiosk, always comes up | unit |
| F12, developer tools, view-source:, file:, data:, javascript:, about: | Developer extras off; only http(s) to the exam servers is ever navigated to; there is no address bar | CI (real WebKit) |
| Ctrl+P/S/O/N/T/W/Q/L/U, F5–F7, F11, Ctrl+Shift+I/J/C/K | Filtered at the kiosk window before WebKit sees them; typing, copy and paste inside the exam still work | CI (xdotool) |
| Print and print preview | `print` signal swallowed: no dialog | CI |
| New windows and tabs | Opened in place if allowed, refused otherwise; never a second window | CI |
| Downloads | Refused in the response policy and cancelled in the web context | CI |
| Drag and drop | Drop target removed from the view | CI |
| Screenshots and screen recording | No key bindings in the exam session (Print Screen does nothing), no way to start a program, WebKit permission requests (screen, camera, microphone) denied, JavaScript clipboard access off | VM, CI |
| Clipboard | Cleared at session start and end by the session script and the kiosk; the clipboard's owner dies with the session anyway | VM |
| Kiosk crash or kill | The session ends. It is never restarted and nothing else is started, so there is no path to a desktop | VM |
| Changing the clock | The lab account can't (not root, and every polkit action is denied to it); the kiosk's exam timer counts with the monotonic clock | VM |
| DNS tunnelling, other DNS servers, DNS over HTTPS/TLS, mDNS | The lab account gets no DNS at all, not even the local resolver: exam servers are pinned in a managed block of `/etc/hosts`; the firewall drops everything that isn't the exam servers' web ports, loopback included. Pins are refreshed from DNS by root (bypassing the block); offline, the last known addresses are kept | VM, unit |
| sudo, su, pkexec, a shell | Lab account not in sudo, password locked, every polkit action denied (`Action=*`), login shell `/usr/lib/primers/exam-shell` (refuses to run; a registered shell so the account stays on the login screen) | VM |
| BIOS, boot from USB, opening the case | Can't be enforced by the OS. The pilot guide requires a firmware password, USB/network boot off, boot order locked, and Secure Boot on | — |

## Consequences

- "VM" tests run in `.github/workflows/build-iso.yml` against the built
  image, booted in QEMU with KVM: keys are sent through QMP and the guest is
  checked through `qemu-guest-agent`. The agent ships in the image but only
  starts when a VM provides its virtio channel (the build fails if its unit
  is not bound to that device), so it is inert on real PCs. "CI" tests run
  on every push with real WebKit under Xvfb; "unit" tests on every push.
- A staff member using the PC's desktop when the exam starts keeps a
  working console until they sign out; `primers-exam start` says so.
- The pinned `/etc/hosts` block affects every account on the PC while the
  exam runs, which is what an exam PC wants.
- Exam sites that need more servers than the ones listed fail visibly
  (refused, logged) rather than silently reaching them.
