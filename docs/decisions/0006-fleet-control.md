# 0006 — primers-fleet: the invigilator's PC controls the lab PCs

- **Status:** accepted
- **Date:** 2026-11-25
- **Builds on:** [0002](0002-exam-mode-lockdown.md), [0004](0004-exam-power-cuts.md), [0005](0005-exam-sites-allow-list.md)

## Context

An invigilator running a CBT exam in a lab of 30–100 PCs has to start the
exam on every PC, see which PCs are ready, which have a candidate signed
in and which have problems, stop the exam everywhere, and keep every PC's
exam log. Walking to each PC with `sudo primers-exam` doesn't scale, and
whatever lets one PC control another is an attack path: a candidate's own
laptop on the lab network must never be able to stop an exam, and nobody
may impersonate the invigilator's PC or a lab PC.

## Decisions

| Concern | Decision | Test |
|---|---|---|
| Identity | Each PC makes its own ECDSA P-256 key and a self-signed certificate the first time `primers-fleet` needs them (`/etc/primers/fleet/identity`, the key readable by root only). The fingerprint (SHA-256 of the certificate) names a PC to people. No central authority, no accounts, nothing to renew. | unit |
| Pairing | `sudo primers-fleet pair` on the invigilator's PC shows a one-time code (12 characters, ~59 bits, from an alphabet without look-alike characters) and opens port 7481 for the pairing only (15 minutes by default). On each lab PC, `sudo primers-fleet join <invigilator PC> <code>`. Both sides exchange certificates and prove they know the code: an HMAC over both nonces and both certificates' fingerprints, keyed by the code stretched with scrypt (n=2^14), so a recorded pairing can't be used to guess the code offline and a party without the code can't pair or sit in the middle. The lab PC checks the invigilator's proof before sending its own; five wrong proofs close the pairing. | unit (pairing, wrong code both ways, the failure limit, names told apart), VM |
| Control channel | TCP 7480 on each lab PC, TLS 1.3 only, both certificates required and checked against the paired ones only (the lab PC trusts only its paired invigilator PCs; the invigilator PC trusts each lab PC's own certificate, and checks the fingerprint again). Host names are not used for identity. | unit (an unpaired controller, a PC that left, an impostor answering at a lab PC's address, TLS 1.2), VM |
| Firewall | The image denies incoming connections (ufw). `join` allows port 7480 only from the address the invigilator's PC paired from; `leave` removes it. `pair` opens 7481 while it runs, and closes it however it ends. | unit (the rules), VM (another lab PC can't reach the port; the pairing port is closed afterwards) |
| What a lab PC will do | Only `ping`, `status`, `exam-start` (an http/https address and `--allow` entries, validated, passed as separate arguments to `primers-exam start`, never through a shell), `exam-stop` and `exam-log` (the exam log, with its SHA-256). Anything else is refused and logged. No shell, no file access, no Lab Mode changes, no software installs. | unit (bad addresses and options never reach `primers-exam`; unknown commands refused) |
| Audit | Both sides append every command, pairing, refusal and departure to `/var/log/primers/fleet.jsonl`, one JSON line each, fsync'd: who (fingerprint), from where, what, the result. Refused connections are logged at most once a minute per address. | unit, VM |
| Logs | `primers-fleet collect DIR` copies each PC's exam log into `DIR/<pc>/exam.jsonl`, checks each against the SHA-256 the PC sent, and writes `SHA256SUMS`. | unit, VM (`sha256sum -c`) |

## Alternatives not taken

- **SSH with keys:** a shell for the invigilator on every lab PC is far
  more than starting and stopping exams, and key management by hand.
- **A central server (cloud or campus):** needs a server and internet the
  pilot labs don't reliably have, and a single place to attack.
- **Trust on first use without a code:** the first PC to answer would be
  trusted; on a shared LAN that can be anyone's laptop.
- **A short (6-digit) code:** online guessing is limited, but a recorded
  pairing would let anyone guess a short code offline; 12 characters with
  scrypt make that impractical.
- **Discovery broadcasts (mDNS):** extra listening services on every
  exam PC. The invigilator's PC learns each lab PC's address when it joins.

## Consequences

- One invigilator PC can control many labs; a lab PC can be paired with
  more than one invigilator PC (each `join` adds one). `primers-fleet
  leave` on a lab PC forgets them all; `primers-fleet forget NAME` on the
  invigilator's PC forgets one lab PC.
- If the invigilator PC's address changes (DHCP), lab PCs' firewalls
  still allow only the old one: run `join` again (pilot guide). A lab PC
  whose address changed shows as unreachable until it joins again.
- The agent runs as root (it starts Exam Mode), only on a paired PC
  (`ConditionDirectoryNotEmpty=/etc/primers/fleet/controllers`), and only
  the listed commands reach it.
- The invigilator's PC holds the key that controls the lab: it must be a
  staff machine kept with the invigilator, not a lab PC.
- Rollback: `primers-fleet leave` on each lab PC; an image without
  primers-fleet ignores `/etc/primers/fleet`. Exam Mode works the same with
  or without it.
