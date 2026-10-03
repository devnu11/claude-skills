#!/bin/sh
# Symlink every skill in this repo into ~/.claude/skills/.
#
# Only touches symlinks that point back into this repo: skills synced from the
# Anthropic account (~/.claude/skills/synced/) and hand-made skill directories
# are left alone.

set -eu

REPO=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

run() {
	if [ "$DRY" -eq 1 ]; then
		printf 'would: %s\n' "$*"
	else
		"$@"
	fi
}

[ -d "$DEST" ] || run mkdir -p "$DEST"

# --- link skills --------------------------------------------------------
found=0
for skill in "$REPO"/*/; do
	[ -f "$skill/SKILL.md" ] || continue
	name=$(basename "$skill")
	target="$DEST/$name"
	found=$((found + 1))

	if [ -L "$target" ]; then
		current=$(readlink "$target")
		if [ "$current" = "${skill%/}" ]; then
			printf 'ok       %s\n' "$name"
			continue
		fi
		printf 'relink   %s\n' "$name"
		run rm -f "$target"
	elif [ -e "$target" ]; then
		printf 'SKIP     %s (exists and is not a symlink)\n' "$name" >&2
		continue
	else
		printf 'link     %s\n' "$name"
	fi
	run ln -s "${skill%/}" "$target"
done

# --- prune links to skills that no longer exist -------------------------
for target in "$DEST"/*; do
	[ -L "$target" ] || continue
	dest=$(readlink "$target")
	case "$dest" in
		"$REPO"/*) ;;
		*) continue ;;          # not ours; leave it
	esac
	[ -f "$dest/SKILL.md" ] && continue
	printf 'prune    %s\n' "$(basename "$target")"
	run rm -f "$target"
done

printf '\n%d skill(s) in %s -> %s\n' "$found" "$REPO" "$DEST"
