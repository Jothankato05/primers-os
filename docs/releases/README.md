# Publishing a PRIMERS OS pre-release

Release notes live here, one file per tag (`v1.0.0-rc1.md`): what was
tested and what wasn't. The release workflow adds the download and
verification instructions, and a fresh machine runs those instructions
against the published release before it counts as done.

## Why the workflow can't always create the tag itself

The workflow's own token (`GITHUB_TOKEN`) creates the release, and with it
the tag. GitHub refuses that token a new tag (or branch) on a commit that
changes files under `.github/workflows/` compared with the default
branch: that needs the `workflows` permission, which `GITHUB_TOKEN` can
never be given. The refusal reads "Resource not accessible by integration"
(HTTP 403), the same as a missing permission, which makes it easy to
mistake for one.

This was proven for v1.0.0-rc1 (CI run 70, a one-off probe): with the same
token and `contents: write`, a tag on `master`'s commit, or on the last
commit before this branch first changed a workflow file, was created (and
deleted again); a tag on the first commit that changes a workflow file, or
on rc1's commit, was refused with exactly that 403. The repository has no
rulesets and is owned by a user, not an organisation, and the token had
**Contents: write** in every run (the job log's "GITHUB_TOKEN Permissions"
group), so neither the Workflow permissions setting nor an organisation
policy was the cause.

So, when the commit to release changes workflow files compared with the
default branch (as every commit on the working branch does until it is
merged), the **tag is made by hand** by someone with write access, and the
workflow then publishes the release on that tag. It accepts an existing tag
only if it points at exactly the commit that was built, and only if no
release exists for it yet (`primers-distro/tools/check-release-tag.sh`,
tested in CI); otherwise it stops before publishing anything.

The repository setting **Settings → Actions → General → Workflow
permissions** can stay on either choice: the jobs ask for what they need
(`contents: write` to create the release, `id-token: write` to sign the
checksums, `actions: read` to reuse a run).

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

When the commit changes workflow files (above), make the tag first, on
exactly the commit the run built, from a clone with write access:

```bash
git fetch origin
git tag v1.0.0-rc1 <commit the run built>
git push origin v1.0.0-rc1
```

Pushing a `v*` tag also starts a fresh build of that tag, which would
publish on its own when it finishes; when publishing an earlier run's ISO,
cancel that build (Actions tab) and run the workflow with
**reuse_run_id** as above.

Either way nothing is published unless every build, signing and VM-test
step passed. A run started with **scenario: performance** (measurements,
docs/benchmarks.md) refuses a tag and keeps no ISO, so it can't be
published either. A tag that exists is never moved, and a release is never
attached to a tag on another commit; a final release (`v1.0.0`) is only
ever a draft, published by hand.
