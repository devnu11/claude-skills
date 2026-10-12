#!/bin/sh
# Build a pinned copy of the runner from an accepted commit (s62 P1-P3).
# Usage: sh agile-team/runner/scripts/pin-runner.sh <commit>
set -eu

die() {
    echo "pin-runner: $1" >&2
    exit "${2:-1}"
}

[ "$#" -eq 1 ] || die "usage: pin-runner.sh <commit>" 2
commit=$1
root=$(git rev-parse --show-toplevel 2>/dev/null) || die "not a git repository"
cd "$root"
sha=$(git rev-parse --verify --quiet "${commit}^{commit}") || die "unknown commit: $commit"
git merge-base --is-ancestor "$sha" HEAD ||
    die "$commit is not on the checked-out branch; pin only accepted code"
git cat-file -e "$sha:agile-team/runner/pyproject.toml" 2>/dev/null ||
    die "$commit has no agile-team/runner"
pid=$(cat .team/run/runner.pid 2>/dev/null || true)
if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    die "the team is running; stop it first"
fi

run=.team/run
rm -rf "$run/runner-pin.new"
mkdir -p "$run/runner-pin.new"
git archive "$sha" agile-team/runner | tar -x -C "$run/runner-pin.new" --strip-components=2
rm -rf "$run/runner-pin"
mv "$run/runner-pin.new" "$run/runner-pin"
echo "$sha" > "$run/runner-pin.commit"
short=$(echo "$sha" | cut -c1-7)
echo "pinned $short at .team/run/runner-pin; run it with: uv run --frozen --quiet --project .team/run/runner-pin agile-team …"
