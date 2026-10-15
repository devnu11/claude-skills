#!/bin/sh
# Build a pinned copy of the runner from an accepted commit (s62 P1-P3), keeping the old pin
# as runner-pin.prev; --rollback restores it (s128 P6, P7).
# Usage: sh agile-team/runner/scripts/pin-runner.sh <commit> | --rollback
set -eu

die() {
    echo "pin-runner: $1" >&2
    exit "${2:-1}"
}

run=.team/run

refuse_if_running() {
    pid=$(cat "$run/runner.pid" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        die "the team is running; stop it first"
    fi
}

# move_pair <from> <to>: move a pin directory and its commit file, each only if present.
move_pair() {
    [ ! -e "$run/$1" ] || mv "$run/$1" "$run/$2"
    [ ! -e "$run/$1.commit" ] || mv "$run/$1.commit" "$run/$2.commit"
}

drop_pair() {
    rm -rf "$run/$1" "$run/$1.commit"
}

rollback() {
    refuse_if_running
    [ -d "$run/runner-pin.prev" ] || die "no previous pin to roll back to"
    drop_pair runner-pin.failed
    move_pair runner-pin runner-pin.failed
    move_pair runner-pin.prev runner-pin
    short=$(cut -c1-7 "$run/runner-pin.commit" 2>/dev/null || true)
    echo "rolled back to $short at .team/run/runner-pin"
}

pin() {
    commit=$1
    sha=$(git rev-parse --verify --quiet "${commit}^{commit}") || die "unknown commit: $commit"
    git merge-base --is-ancestor "$sha" HEAD ||
        die "$commit is not on the checked-out branch; pin only accepted code"
    git cat-file -e "$sha:agile-team/runner/pyproject.toml" 2>/dev/null ||
        die "$commit has no agile-team/runner"
    refuse_if_running
    rm -rf "$run/runner-pin.new"
    mkdir -p "$run/runner-pin.new"
    git archive "$sha" agile-team/runner | tar -x -C "$run/runner-pin.new" --strip-components=2
    drop_pair runner-pin.prev
    move_pair runner-pin runner-pin.prev
    mv "$run/runner-pin.new" "$run/runner-pin"
    echo "$sha" > "$run/runner-pin.commit"
    short=$(echo "$sha" | cut -c1-7)
    echo "pinned $short at .team/run/runner-pin; run it with: uv run --frozen --quiet --project .team/run/runner-pin agile-team …"
}

[ "$#" -eq 1 ] || die "usage: pin-runner.sh <commit> | --rollback" 2
root=$(git rev-parse --show-toplevel 2>/dev/null) || die "not a git repository"
cd "$root"
if [ "$1" = "--rollback" ]; then rollback; else pin "$1"; fi
