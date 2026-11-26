#!/bin/bash
# Tests for tools/check-release-tag.sh, the check before a release is
# published for a tag: with a fake gh that answers from fixture files
# (and applies --jq with the real jq), so no network and no token.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
check_tag="$here/tools/check-release-tag.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fails=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }

mkdir -p "$work/bin" "$work/api"
# A fake gh: "gh api [--paginate] PATH --jq EXPR" prints the fixture for
# PATH through jq; no fixture is an API error (exit 1)
cat > "$work/bin/gh" <<FAKE
#!/bin/bash
[ "\$1" = api ] || exit 2
shift
path="" expr="."
while [ \$# -gt 0 ]; do
    case "\$1" in
        --paginate) ;;
        --jq) expr="\$2"; shift ;;
        *) path="\$1" ;;
    esac
    shift
done
file="$work/api/\$(printf '%s' "\$path" | tr '/?&=' '____')"
[ -f "\$file" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
jq -r "\$expr" "\$file"
FAKE
chmod +x "$work/bin/gh"
export PATH="$work/bin:$PATH" GITHUB_REPOSITORY=acme/os

built=1111111111111111111111111111111111111111
other=2222222222222222222222222222222222222222
fixture() { printf '%s' "$2" > "$work/api/$(printf '%s' "$1" | tr '/?&=' '____')"; }
reset() { rm -f "$work/api/"*; fixture "repos/acme/os/releases?per_page=100" '[]'; }
refs() { fixture "repos/acme/os/git/matching-refs/tags/v1.0.0-rc1" "$1"; }

# run NAME WANT_EXIT WANT_OUTPUT [TAG] [COMMIT]
run() {
    local out rc=0
    out=$("$check_tag" "${4:-v1.0.0-rc1}" "${5:-$built}" 2> "$work/err") || rc=$?
    if [ "$rc" -eq "$2" ] && [ "$out" = "$3" ]; then
        pass "$1"
    else
        fail "$1 (exit $rc, output '$out', want exit $2 '$3'; $(cat "$work/err"))"
    fi
}

reset; refs '[]'
run "no tag yet: the release creates it" 0 new

reset; refs "[{\"ref\":\"refs/tags/v1.0.0-rc1\",\"object\":{\"type\":\"commit\",\"sha\":\"$built\"}}]"
run "a tag made by hand on the built commit is used" 0 existing

reset; refs "[{\"ref\":\"refs/tags/v1.0.0-rc1\",\"object\":{\"type\":\"commit\",\"sha\":\"$other\"}}]"
run "a tag on another commit is refused (never moved, never mismatched)" 1 ""

reset; refs '[{"ref":"refs/tags/v1.0.0-rc1","object":{"type":"tag","sha":"aaaa"}}]'
fixture "repos/acme/os/git/tags/aaaa" "{\"object\":{\"type\":\"commit\",\"sha\":\"$built\"}}"
run "an annotated tag is followed to its commit" 0 existing

reset; refs '[{"ref":"refs/tags/v1.0.0-rc1","object":{"type":"tag","sha":"aaaa"}}]'
fixture "repos/acme/os/git/tags/aaaa" "{\"object\":{\"type\":\"commit\",\"sha\":\"$other\"}}"
run "an annotated tag on another commit is refused" 1 ""

reset; refs '[{"ref":"refs/tags/v1.0.0-rc1","object":{"type":"tag","sha":"aaaa"}}]'
run "an annotated tag that can't be read is refused" 1 ""

reset; refs "[{\"ref\":\"refs/tags/v1.0.0-rc10\",\"object\":{\"type\":\"commit\",\"sha\":\"$other\"}}]"
run "a longer tag with the same start (v1.0.0-rc10) is not taken for it" 0 new

reset; refs "[{\"ref\":\"refs/tags/v1.0.0-rc1\",\"object\":{\"type\":\"commit\",\"sha\":\"$built\"}}]"
fixture "repos/acme/os/releases?per_page=100" '[{"id":7,"tag_name":"v1.0.0-rc1","draft":true}]'
run "a release for the tag already exists (even a draft): refused" 1 ""

reset; refs '[]'
fixture "repos/acme/os/releases?per_page=100" '[{"id":8,"tag_name":"v1.0.0-rc2","draft":false}]'
run "another tag's release doesn't matter" 0 new

reset
run "the tag can't be looked up (API error): refused" 1 ""

reset; refs '[]'
run "a short or malformed commit ID is refused" 1 "" v1.0.0-rc1 1111111

reset; refs '[]'; rm -f "$work/api/"*releases*
run "the releases can't be listed (API error): refused" 1 ""

echo
if [ "$fails" -eq 0 ]; then echo "all passed"; else echo "$fails failed"; exit 1; fi
