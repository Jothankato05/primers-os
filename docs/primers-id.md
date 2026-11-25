# Primers ID on PRIMERS OS

`primers-id` signs the person at the desktop in with their Primers ID, using
OpenID Connect. Decisions and limits: [ADR 0007](decisions/0007-primers-id.md).

> **Status:** the live Primers ID service isn't running yet. Until it is,
> `primers-id login` says the provider can't be reached. Everything below
> is tested against a mock provider in virtual machines and in unit tests.

## Signing in

```bash
primers-id login
```

1. You are asked to choose a **PIN** (4 or more digits) for signing in when
   the internet is down. Press Enter to skip it (`--no-pin` skips the
   question).
2. The command shows an address and a code, for example:

   ```
   To sign in, open this address on this PC or your phone:

     https://id.primersgroup.ng/activate?code=4F2A-91C3

   and enter the code:  4F2A-91C3
   ```

3. Open the address (on the PC or on your phone), sign in to Primers ID
   there, and approve. The command finishes with
   `Signed in as <name> <email> (online).`

PRIMERS OS never asks for your Primers password itself: you only type it at
the Primers ID page. If the provider doesn't offer codes, the command opens
the browser on this PC instead (`primers-id login --browser` does that on
purpose).

## When the internet is down

```bash
primers-id login --offline
```

Type the PIN you chose. This works for 14 days after your last online
sign-in on this PC (the number of days is set by the lab's administrator).
After five wrong PINs, offline sign-in is locked until you sign in online
again. If Primers ID can't be reached, `primers-id login` says so and points
to `--offline` (exit code 2).

Offline sign-in only confirms on this PC that you are the person who last
signed in here. It gives no access to anything online.

## Who is signed in, and signing out

```bash
primers-id status            # or: primers-id status --json
primers-id logout
```

`logout` tells the provider to forget this PC's sign-in and deletes it from
the PC. On a Lab Mode PC the shared account's files, the sign-in included,
are wiped after every session anyway, but please sign out on shared PCs.

Your sign-in is kept in `~/.local/share/primers/id/session.json`, readable
by you only. It holds your Primers ID number, name and email, when you last
signed in online, the token that renews the sign-in, and your PIN as a
one-way hash (never the PIN itself).

## For administrators: choosing the provider

The provider is set in `/etc/primers/id.conf`:

```ini
[primers-id]
issuer = https://id.primersgroup.ng
client_id = primers-os
scopes = openid profile email
offline_days = 14
```

- **issuer**: the provider's address; its
  `/.well-known/openid-configuration` must be there and must name the same
  issuer. It must be `https` (plain `http` only for a provider on the PC
  itself, or with `allow_http = true` for tests: never on real networks).
- **client_id**: PRIMERS OS's client ID at that provider. Register it as a
  **public client** (no secret) that may use the device flow
  (`urn:ietf:params:oauth:grant-type:device_code`) and/or the authorization
  code flow with PKCE (S256) with the redirect `http://127.0.0.1:<any
  port>/callback`, and refresh tokens. ID tokens signed with RS256 or ES256.
- **offline_days**: how long the offline PIN works after the last online
  sign-in.
- **timeout** (optional): seconds to wait for the provider (default 10).

Moving to the real Primers ID service, or a campus provider, is a change to
this file only. People sign in again afterwards: a session from another
issuer isn't used.

## Testing with the mock provider

```bash
cd primers-os
python3 tests/mock_oidc.py --port 8790        # prints its issuer
python3 -m pytest tests/test_primers_id.py
```

The mock provider (never for real use) signs a test person in at once and
approves device codes with `POST /test/approve` (`user_code=...`). The VM test
`primers-distro/tests/vm/run_vm_tests.py primers-id` runs it on the host and
signs in from a running PRIMERS OS: the device flow, the session's file
permissions, the provider blocked (the hint to sign in offline, a wrong PIN
refused, the right PIN accepted) and signing out (the refresh token
revoked).
