#!/bin/sh
# Guards the repo against chezmoi source-state names. POSIX sh:
# `sh tests/chezmoi_names_test.sh`.
#
# devnu11/home ships these skills as a submodule inside its chezmoi source
# directory, so chezmoi reads every path here as source state. A file named
# run_x.py is executed as a script on apply instead of being copied, and
# prefixes such as dot_ or exact_ rename or change the file. Every tracked
# path component must therefore avoid chezmoi's prefixes and suffixes.

set -u

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PREFIXES='after_|before_|create_|dot_|empty_|encrypted_|exact_|executable_|external_|literal_|modify_|once_|onchange_|private_|readonly_|remove_|run_|symlink_'
SUFFIXES='\.(tmpl|age|asc)$'
FAILED=0

# The path components among stdin's paths that chezmoi would treat specially.
find_reserved() {
	tr '/' '\n' | grep -E "^($PREFIXES)|$SUFFIXES" | sort -u
}

# Fails the run unless find_reserved prints exactly $2 for the paths in $1.
expect() {
	found=$(printf '%s\n' "$1" | find_reserved)
	if [ "$found" != "$2" ]; then
		echo "FAIL: for '$1' expected '$2', got '$found'"
		FAILED=1
	fi
}

expect "skill/runner/run_writer.py" "run_writer.py"
expect "skill/exact_dir/file.md" "exact_dir"
expect "skill/notes.tmpl" "notes.tmpl"
expect "skill/runner/state_writer.py
skill/tests/test_run.py" ""

reserved=$(git -C "$HERE/.." ls-files | find_reserved)
if [ -n "$reserved" ]; then
	echo "FAIL: chezmoi would not copy these names as-is (rename them):"
	# shellcheck disable=SC2086 # one name per line on purpose
	printf '  %s\n' $reserved
	FAILED=1
fi

[ "$FAILED" -eq 0 ] && echo "chezmoi names: ok"
exit "$FAILED"
