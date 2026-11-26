#!/bin/bash
# check-release-tag.sh TAG COMMIT
#
# Before a release is published for TAG on COMMIT (the commit that was
# built). Prints "new" when the tag doesn't exist yet (the release creates
# it on COMMIT), or "existing" when it already exists and points at exactly
# COMMIT (made by hand: the workflow's own token can't create a tag on a
# commit that changes workflow files, docs/releases/README.md). Fails when
# the tag points anywhere else (a published tag is never moved, and a
# release must never be attached to a tag on another commit) or when a
# release for TAG already exists. Any API error fails too: nothing is
# published on a guess.
#
# Needs gh with GH_TOKEN, and GITHUB_REPOSITORY.
set -euo pipefail

tag=${1:?usage: check-release-tag.sh TAG COMMIT}
commit=${2:?usage: check-release-tag.sh TAG COMMIT}
repo=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}

if ! printf '%s' "$commit" | grep -Eq '^[0-9a-f]{40}$'; then
    echo "::error::'$commit' is not a full commit ID" >&2
    exit 1
fi

# Exact match only (matching-refs is a prefix match); an empty list is fine
refs=$(gh api "repos/$repo/git/matching-refs/tags/$tag" \
    --jq ".[] | select(.ref == \"refs/tags/$tag\") | \"\(.object.type) \(.object.sha)\"")

state=new
if [ -n "$refs" ]; then
    read -r type sha <<< "$refs"
    # An annotated tag points at a tag object: follow it to the commit
    for _ in 1 2 3 4 5; do
        [ "$type" = tag ] || break
        read -r type sha <<< "$(gh api "repos/$repo/git/tags/$sha" --jq '"\(.object.type) \(.object.sha)"')"
    done
    if [ "$type" != commit ] || [ "$sha" != "$commit" ]; then
        echo "::error::tag $tag already exists on $type $sha, not on $commit, the commit that was built; a published tag is never moved" >&2
        exit 1
    fi
    state=existing
fi

# Drafts included (the token can see them); paginated
existing=$(gh api --paginate "repos/$repo/releases?per_page=100" \
    --jq ".[] | select(.tag_name == \"$tag\") | \"\(.id) draft=\(.draft)\"")
if [ -n "$existing" ]; then
    echo "::error::a release for $tag already exists ($existing); it is not replaced" >&2
    exit 1
fi

echo "$state"
