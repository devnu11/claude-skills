# ADR-012: Rebase the team branch onto upstream at sprint start

Status: accepted (s59). Date: 2026-10-12. Design: [`../design/s59.md`](../design/s59.md).
Supersedes ADR-005 decision 1 ("Merge in, never rewrite"). ADR-005's other
decisions stand.

## Context

ADR-005 merged `<remote>/<branch>` into the team branch at each sprint start
so that no recorded hash would ever go stale. Main, though, receives each
sprint as rebased copies ("Rebase and merge"). Sometimes the team branch
still holds the originals plus later commits that edit the same lines.
Merging main in then conflicts on content that is already the same: about
100 false conflicts at sprint 18 (m54). The liaison fixed it by hand with
a rebase and rewrote the story hashes in `state.json` by hand. The human
ruled (2026-10-11): rebase, never merge, at the sprint boundary. Hashes
matter only within a sprint.

## Decision

1. At sprint start the runner rebases the team branch onto
   `<remote>/<branch>`, non-interactively. Commits whose patch is already
   upstream are dropped, so are merge commits, and so are commits that
   become empty. There is no merge and no `-s ours`/`-X ours`.
2. It pairs each old commit with its rebased copy by what a rebase keeps
   (author, author date, message), in order. A dropped commit maps to the
   last kept copy before it, or to the target. It then rewrites the team
   hashes recorded in `state.json`. The last-checked sha is not rewritten,
   so the full checks run again on the new tree.
3. It checks that no content was lost: a path that only one side touched
   must keep that side's version. Otherwise it resets the branch to where
   it was and holds with an error.
4. A real conflict aborts the rebase (the branch is unchanged) and holds
   `sync_conflict`. The human rebases by hand. On `continue_boundary` the
   runner pairs from the HEAD it recorded at the boundary's first sync, so
   a hand rebase is remapped the same way.
5. Pushing is unchanged: only review branches, with `--force-with-lease`.
   The team branch is never pushed.

## Alternatives rejected

- **Keep merging, resolve with `-X ours`/`-s ours`.** That hides real
  conflicts and can silently drop upstream changes.
- **Pair by patch id.** Patch ids change when context lines shift, and that
  is exactly what happens on a rebase over nearby upstream edits.
- **`post-rewrite` hook or `--update-refs`.** These need hooks or git 2.38,
  and they say nothing about a rebase the human does by hand.

## Consequences

- Hashes quoted in reviews, stories and designs before a sprint start stay
  as historical text. The old commits stay reachable only through other
  refs and the reflog.
- The team branch's history is linear. Main can take it with "Rebase and
  merge" without false conflicts.
- A sync that rebased always re-runs the full checks.
