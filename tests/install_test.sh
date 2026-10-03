#!/bin/sh
# Tests for install.sh. POSIX sh, no dependencies: `sh tests/install_test.sh`.
#
# Each test gets a scratch copy of install.sh beside a few fake skills, and a
# scratch destination, so nothing touches the real ~/.claude/skills. install.sh
# links whatever sits beside it, which is what lets the tests add and remove
# skills freely.

set -u

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
INSTALL="$HERE/../install.sh"
FAILED=0
PASSED=0

# --- fixture ------------------------------------------------------------

# Create the scratch area. Sets SCRATCH, WORK, REPO and DEST. WORK has a
# space in it so every test also covers quoting.
setup() {
	SCRATCH=$(mktemp -d) || exit 1
	WORK="$SCRATCH/with space"
	mkdir -p "$WORK/repo"
	REPO=$(CDPATH='' cd -- "$WORK/repo" && pwd)
	DEST="$WORK/dest"
	populate_repo
}

# install.sh beside skills alpha and beta, and a directory without SKILL.md.
populate_repo() {
	cp "$INSTALL" "$REPO/install.sh"
	add_skill alpha
	add_skill beta
	mkdir "$REPO/notes"
}

teardown() {
	rm -rf "$SCRATCH"
}

add_skill() {
	mkdir -p "$REPO/$1"
	printf -- '---\nname: %s\n---\n' "$1" >"$REPO/$1/SKILL.md"
}

# Run install.sh against DEST. stdout goes to $WORK/out, stderr to $WORK/err.
run_install() {
	run_install_via "$REPO/install.sh" "$@"
}

# Like run_install, but runs the script at path $1 (e.g. a symlink to it).
run_install_via() {
	script=$1
	shift
	CLAUDE_SKILLS_DIR="$DEST" sh "$script" "$@" >"$WORK/out" 2>"$WORK/err"
}

# One line per entry in DEST: inode, name, and link target (or "-" for
# non-links). The inode changes if a link is deleted and recreated, even with
# the same target.
snapshot() {
	for entry in "$DEST"/*; do
		[ -e "$entry" ] || [ -L "$entry" ] || continue
		# Only the leading inode field is used, so odd names can't break it.
		# shellcheck disable=SC2012
		inode=$(ls -di "$entry" | awk '{print $1}')
		printf '%s %s %s\n' "$inode" "$(basename "$entry")" "$(link_target "$entry")"
	done
}

# Where a symlink points, or "-" for anything else.
link_target() {
	if [ -L "$1" ]; then readlink "$1"; else echo -; fi
}

# --- assertions ---------------------------------------------------------

# Record a failure. Tests keep running after one, so a single run reports
# every broken expectation; run_test checks the record afterwards.
fail() {
	printf '    %s\n' "$*" >>"$WORK/failures"
}

assert_linked() {
	[ -L "$DEST/$1" ] || { fail "$1: not a symlink"; return; }
	actual=$(readlink "$DEST/$1")
	[ "$actual" = "$REPO/$1" ] || fail "$1: points at $actual, want $REPO/$1"
}

assert_absent() {
	if [ -e "$DEST/$1" ] || [ -L "$DEST/$1" ]; then
		fail "$1: should not exist"
	fi
}

assert_contains() {
	grep -q -- "$2" "$1" || fail "$(basename "$1") lacks '$2': $(cat "$1")"
}

assert_not_contains() {
	! grep -q -- "$2" "$1" || fail "$(basename "$1") has '$2': $(cat "$1")"
}

# Run install.sh with any further arguments and fail if DEST changed at all.
assert_run_changes_nothing() {
	before=$(snapshot)
	run_install "$@" || fail "exit $?"
	after=$(snapshot)
	[ "$before" = "$after" ] || fail "DEST changed: '$before' -> '$after'"
}

# --- tests --------------------------------------------------------------

test_fresh_install_links_every_skill() {
	run_install || fail "exit $?"
	assert_linked alpha
	assert_linked beta
	assert_contains "$WORK/out" 'link     alpha'
}

test_ignores_directories_without_skill_md() {
	run_install || fail "exit $?"
	assert_absent notes
}

test_second_run_is_idempotent() {
	run_install || fail "first run: exit $?"
	# A no-op run needs no writes, so a read-only DEST makes any rm or ln
	# fail loudly. (Root ignores the mode; the inode comparison still holds.)
	chmod a-w "$DEST"
	assert_run_changes_nothing
	chmod u+w "$DEST"
	assert_contains "$WORK/out" 'ok       beta'
	! grep -Eq '^(link|relink|prune) ' "$WORK/out" || fail "second run acted: $(cat "$WORK/out")"
}

test_dry_run_changes_nothing() {
	run_install --dry-run || fail "exit $?"
	[ ! -e "$DEST" ] || fail "dry run created $DEST"
	assert_contains "$WORK/out" 'would: ln -s'
}

test_dry_run_leaves_existing_links_alone() {
	run_install || fail "first run: exit $?"
	ln -sf "$WORK" "$DEST/alpha"
	rm -rf "${REPO:?}/beta"
	assert_run_changes_nothing --dry-run
	assert_contains "$WORK/out" 'would: rm -f'
}

test_relinks_link_pointing_elsewhere() {
	mkdir -p "$DEST" "$WORK/old/alpha"
	ln -s "$WORK/old/alpha" "$DEST/alpha"
	run_install || fail "exit $?"
	assert_linked alpha
	assert_contains "$WORK/out" 'relink   alpha'
}

test_skips_real_directory_in_the_way() {
	mkdir -p "$DEST/alpha"
	run_install || fail "exit $?"
	if [ -L "$DEST/alpha" ] || [ ! -d "$DEST/alpha" ]; then
		fail "alpha was replaced"
	fi
	assert_contains "$WORK/err" 'SKIP     alpha'
}

test_prunes_link_to_deleted_skill() {
	run_install || fail "first run: exit $?"
	rm -rf "${REPO:?}/beta"
	run_install || fail "exit $?"
	assert_absent beta
	assert_linked alpha
	assert_contains "$WORK/out" 'prune    beta'
}

test_prunes_link_when_only_skill_md_is_gone() {
	run_install || fail "first run: exit $?"
	rm -f "$REPO/beta/SKILL.md"
	run_install || fail "exit $?"
	assert_absent beta
}

test_leaves_foreign_entries_alone() {
	mkdir -p "$DEST/synced" "$WORK/elsewhere/gone"
	ln -s "$WORK/elsewhere/gone" "$DEST/foreign"
	rm -rf "$WORK/elsewhere/gone"
	run_install || fail "exit $?"
	[ -d "$DEST/synced" ] || fail "synced/ removed"
	[ -L "$DEST/foreign" ] || fail "foreign dangling link pruned"
}

test_runs_through_absolute_symlink() {
	mkdir -p "$WORK/bin"
	ln -s "$REPO/install.sh" "$WORK/bin/install-skills"
	run_install_via "$WORK/bin/install-skills" || fail "exit $?"
	assert_linked alpha
	assert_linked beta
	assert_contains "$WORK/out" "in $REPO ->"
}

test_runs_through_relative_symlink_chain() {
	mkdir -p "$WORK/bin" "$WORK/lib"
	ln -s ../repo/install.sh "$WORK/lib/install.sh"
	ln -s ../lib/install.sh "$WORK/bin/install-skills"
	run_install_via "$WORK/bin/install-skills" || fail "exit $?"
	assert_linked alpha
	assert_linked beta
}

# --- runner -------------------------------------------------------------

run_test() {
	setup
	"$1"
	record_result "$1"
	teardown
}

# Count and print the outcome of the test just run.
record_result() {
	if [ ! -s "$WORK/failures" ]; then
		PASSED=$((PASSED + 1))
		printf 'ok   %s\n' "$1"
		return
	fi
	FAILED=$((FAILED + 1))
	printf 'FAIL %s\n' "$1"
	cat "$WORK/failures"
}

# Every function named test_*, in file order. Names are single words.
# shellcheck disable=SC2013
for t in $(sed -n 's/^\(test_[A-Za-z0-9_]*\)() {$/\1/p' "$HERE/install_test.sh"); do
	run_test "$t"
done

printf '\n%d passed, %d failed\n' "$PASSED" "$FAILED"
if [ $((PASSED + FAILED)) -eq 0 ]; then
	echo 'no tests found' >&2
	exit 1
fi
[ "$FAILED" -eq 0 ]
