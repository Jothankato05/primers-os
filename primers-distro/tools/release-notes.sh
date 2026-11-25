#!/bin/bash
# Release notes for a PRIMERS OS release, printed to stdout:
# docs/releases/<tag>.md followed by download and verification instructions.
#
#   release-notes.sh TAG ISO_NAME SPLIT(true|false) SIGNER_IDENTITY COMMIT
#
# SIGNER_IDENTITY is the workflow identity in SHA256SUMS.pem, e.g.
# https://github.com/OWNER/REPO/.github/workflows/build-iso.yml@refs/heads/BRANCH
# The ```bash blocks are run as-is by the release workflow's verify job on a
# fresh machine, so what users are told to run is exactly what was tested.
set -euo pipefail
tag=$1 iso=$2 split=$3 identity=$4 commit=$5
notes="docs/releases/${tag}.md"
if [ ! -f "$notes" ]; then
  echo "::error::$notes is missing: every release needs notes saying what is tested and what isn't" >&2
  exit 1
fi

cat "$notes"
echo
echo "## Download and verify"
echo
if [ "$split" = "true" ]; then
  echo "The ISO is larger than GitHub's 2 GiB asset limit, so it is split into parts. Download every \`$iso.part*\` file plus \`SHA256SUMS\`, \`SHA256SUMS.sig\` and \`SHA256SUMS.pem\` into one folder, then join the parts:"
  echo
  echo '```bash'
  echo "cat $iso.part* > $iso"
  echo '```'
else
  echo "Download \`$iso\`, \`SHA256SUMS\`, \`SHA256SUMS.sig\` and \`SHA256SUMS.pem\` into one folder."
fi
echo
echo "Check that the checksums file was signed by this repository's release workflow ([cosign](https://docs.sigstore.dev/cosign/system_config/installation/) 2.x):"
echo
echo '```bash'
echo "cosign verify-blob SHA256SUMS --signature SHA256SUMS.sig --certificate SHA256SUMS.pem \\"
echo "  --certificate-identity $identity \\"
echo "  --certificate-oidc-issuer https://token.actions.githubusercontent.com"
echo '```'
echo
echo "Then check the download against it:"
echo
echo '```bash'
echo "sha256sum -c SHA256SUMS --ignore-missing"
echo '```'
echo
echo "Built from commit \`$commit\`."
