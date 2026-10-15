# ADR-0069: One numbered queue for tell, reorder and share files

**Date:** 2026-10-14 · **Story:** s134 · **Design:** `agile-team/docs/design/s134.md`

## Context

Three writers queue files in a numbered folder the same way: write a draft
`.draft-<token>`, hard-link it to the first free `<prefix><N><suffix>` (a link
never overwrites, so a lost race moves on to the next number), then remove the
draft. `relay.Relay.tell` (s62, `t<N>.md`), `reorders.Requests.queue` (s83,
`r<N>.json`) and `sharing.Shares.queue` (s120, `f<N>.json`) each carry their
own copy, with their own name pattern and listing code. The s120 review (F5)
asked for one helper so a fix to the queue lands once.

## Decision

A new module `agile_team/numbered_queue.py` owns the mechanism:
`NumberedQueue(folder, prefix, suffix)` with `publish(text) -> Entry` and
`entries() -> list[Entry]`, where `Entry(id, path)` names one numbered file.
It talks only to `system`. `Relay`, `Requests` and `Shares` each build their
queue and keep only what is theirs: the file's content and how a file is read
back into their own type.

The file names, ids, draft name and the order of operations stay as they are.

## Consequences

- The draft, link and listing code exists once; the three modules shrink to
  their content and parsing.
- `NumberedQueue` has its own tests; the three modules' tests still cover
  their own contents and ids.
- A test that patched `Relay._next_number` now patches
  `NumberedQueue._next_number`, the seam's new home.
- A future numbered folder uses `NumberedQueue` rather than a fourth copy.
