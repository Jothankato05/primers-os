# Publishing a PRIMERS OS pre-release

Release notes live here, one file per tag (`v1.0.0-rc1.md`): what was
tested and what wasn't. The release workflow adds the download and
verification instructions, and a fresh machine runs those instructions
against the published release before it counts as done.

## One-time setting (needed before the first release)

The workflow's own token creates the release. GitHub refuses it
("Resource not accessible by integration", HTTP 403) unless the repository
lets workflows write:

1. GitHub → the repository → **Settings → Actions → General**.
2. Under **Workflow permissions**, choose **Read and write permissions**
   and save. (If the option is greyed out, the organisation's Actions
   settings set it; an organisation owner changes it there.)

The workflow still asks only for what each job needs (`contents: write` to
create the release, `id-token: write` to sign the checksums).

## Publishing

Pre-releases (tags like `v1.0.0-rc1`) are published from the Actions tab:
**Build and Release PRIMERS OS ISO → Run workflow**, on the branch to
release, with:

- **prerelease_tag**: the tag, e.g. `v1.0.0-rc1` (its notes file must be in
  that branch);
- **reuse_run_id** (optional): the ID of an earlier green run of this
  workflow on that branch, to publish the ISO it built and signed instead
  of building again. The run's notes are taken from the commit it built,
  so the notes must have been committed before that run.

Either way nothing is published unless every build, signing and VM-test
step passed. A run started with **scenario: performance** (measurements,
docs/benchmarks.md) refuses a tag and keeps no ISO, so it can't be
published either. A tag that exists is never moved; a final release (`v1.0.0`)
is only ever a draft, published by hand.
