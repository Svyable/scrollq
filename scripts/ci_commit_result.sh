#!/usr/bin/env bash
# Create-only commit of a CI result into artifacts/, safe when several
# workflows push to the same branch: rebase onto the latest branch tip and
# retry. Usage: ci_commit_result.sh <dest_dir> <message> <src> [<src> ...]
set -euo pipefail
dest="$1"; msg="$2"; shift 2
branch="${GITHUB_REF_NAME:?}"
mkdir -p "$dest"
for src in "$@"; do
  name="$(basename "$src")"
  test ! -e "$dest/$name"
  cp "$src" "$dest/$name"
done
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add "$dest"
git commit -m "$msg"
for attempt in 1 2 3 4 5 6; do
  if git pull --rebase origin "$branch" && git push origin "HEAD:$branch"; then
    exit 0
  fi
  sleep $((attempt * 5))
done
echo "could not push result after retries" >&2
exit 1
