# 0007 — Primers ID: signing in with OpenID Connect, online and offline

- **Status:** accepted
- **Date:** 2026-11-25
- **Builds on:** [0002](0002-exam-mode-lockdown.md) (Lab Mode's shared account)

## Context

Primers ID is meant to be one Primers account for every Primers product,
PRIMERS OS included. The live Primers ID service isn't built yet, so the OS
side has to work against any standards-based provider now (a test one, a
campus one) and switch to the real one later without a new release.

PCs in the pilot labs share accounts (Lab Mode) and the internet comes and
goes, so a person must be able to sign in when the provider can't be
reached, and nothing one person leaves behind may help the next person.
Some choices here are hard to undo once people rely on them: the protocol,
where tokens live, and what offline sign-in means.

## Decisions

| Concern | Decision | Test |
|---|---|---|
| Protocol | OpenID Connect, with the provider found by discovery (`/.well-known/openid-configuration`). The OS is a **public client** (no client secret: anything shipped on every PC isn't secret). | unit, VM |
| Sign-in flow | The **device flow** (RFC 8628) when the provider offers it: `primers-id login` shows an address and a short code, and the person approves on this PC's browser or on their phone. Otherwise the **authorization code flow with PKCE (S256)** through the browser and a one-time loopback address on 127.0.0.1 (RFC 8252), with `state` and `nonce`. No passwords are ever typed into PRIMERS OS itself. | unit (both flows, a refused sign-in, a reply for another sign-in), VM (device flow) |
| Checking the ID token | Signature checked against the provider's JWKS; only RS256 and ES256 (never `none`, never HMAC with a public key); issuer, audience (and `azp`), expiry, issued-at (2 minutes' leeway) and, in the browser flow, nonce. The discovery document must name the configured issuer. A token that fails any check is refused and nothing is kept. | unit (wrong issuer, wrong audience, bad signature, expired, `alg: none`, wrong nonce, a provider claiming another name) |
| Which provider | `/etc/primers/id.conf`: `issuer`, `client_id`, `scopes`, `offline_days`. `https` is required unless the issuer is on this PC (`localhost`) or the file says `allow_http = true` (tests only). Moving to the real Primers ID service, or to a campus provider, is a change to this file only: no code change, no new release. | unit (a second provider by changing the file only), VM (the VM test reconfigures the file) |
| Where the session lives | `~/.local/share/primers/id/session.json`: the directory mode 0700, the file 0600, written atomically. It holds the person's ID (`sub`), name, email, issuer, when they last signed in online, the refresh token, and the offline PIN's scrypt hash. Access and ID tokens aren't kept. `primers-id status` never shows the refresh token or the PIN hash. | unit (modes, the PIN isn't in the file, status hides secrets), VM (modes) |
| Offline sign-in | At an online sign-in the person may choose a PIN (4 or more digits). `primers-id login --offline` accepts that PIN for `offline_days` days (14 by default) after the last online sign-in. Five wrong PINs lock offline sign-in until the next online sign-in. The PIN is stored only as scrypt (n=2^14, r=8, p=1, a random 16-byte salt). | unit (inside and after the window, the lockout and the unlock, a PIN is needed, PINs must be digits), VM (the provider blocked: the command points to offline sign-in, a wrong PIN is refused, the right one works) |
| What offline means | Offline sign-in confirms, on this PC only, that the person at the desktop is the one who last signed in online here. It gives no access to anything on the provider's side and never makes new tokens. | by design |
| Signing out | `primers-id logout` revokes the refresh token at the provider (when it has a revocation endpoint) and deletes the session file. On Lab Mode's shared account the whole home folder, this file included, is wiped after every session. | unit (the provider receives the revocation), VM |

## Limits we accept

- **The PIN protects against a passer-by, not against the account
  itself.** Anyone who can read `session.json` (the person, or root) could
  try every short PIN offline against the scrypt hash. That person already
  has the account; offline sign-in grants nothing beyond it (see "What
  offline means"). A longer PIN is allowed and recommended.
- **On the lab account, a session left signed in is wiped, not revoked.**
  Lab Mode deletes the file after the session, so nobody can use the
  refresh token again from that PC, but the provider only forgets it when it
  expires. Signing out (`primers-id logout`) revokes it. Revoking from Lab
  Mode's cleanup is a possible later improvement.
- **The live Primers ID service doesn't exist yet.** The image names its
  planned address (`https://id.primersgroup.ng`); until it is live,
  `primers-id login` reports that the provider can't be reached. Everything
  is tested against a mock provider (`primers-os/tests/mock_oidc.py`).
- **Command line only for now.** A sign-in window on the desktop (and
  signing in at the login screen) is later work; it will use the same
  module.

## Alternatives not taken

- **Resource-owner password grant (typing the Primers password into the
  OS):** the OS would handle the password, it is deprecated in OAuth 2.1,
  and it rules out two-factor sign-in at the provider.
- **A client secret in the image:** every PC has the same image, so it
  wouldn't be secret; PKCE and the device flow are made for public clients.
- **Keeping tokens in the system keyring:** the lab PCs have no keyring
  unlocked at a password-less lab sign-in, and the file's permissions give
  the same protection on a single-user home; can be revisited for staff
  PCs.
- **Offline sign-in without a PIN (trusting the last session):** on a
  shared PC the next person would inherit the last person's identity.
- **An unlimited offline window:** an account closed at the provider would
  keep working offline forever; 14 days (configurable) bounds that.

## Rollback

Delete `/etc/primers/id.conf` (or don't install it): `primers-id` then says
Primers ID isn't set up and nothing else in the OS depends on it. Sessions
are per-person files that `primers-id logout` (or deleting
`~/.local/share/primers/id`) removes.
