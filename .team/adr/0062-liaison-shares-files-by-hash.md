# ADR-0062: The liaison shares files into the design docs, pinned by SHA-256

Story: s120. Design: `agile-team/docs/design/s120.md`.

## Context

The liaison keeps the human's mocks and specs in `.team/run/liaison/`, which
no role can read. For s118 the team copied a mock by hand, and nothing
stopped a role from editing that copy later. Then the Customer Proxy would
judge the product against a mock the human never approved. The Manager's
proposal m137 (copy with a hash) asks for the same fix.

## Decision

- `agile-team share <file> --story <id>` queues the file's bytes and SHA-256 as
  `.team/run/liaison/shares/f<N>.json`. It never writes the working tree or
  git, so it is safe while a step runs, like `tell`.
- The runner applies queued shares between steps (each router tick, after the
  reorder desk, never while a sprint boundary is open). It copies the file to
  `<docs>/design/<id>-<name>`, records `{path, sha256}` under a `shared:` key
  in the story file's frontmatter, and commits exactly those two paths in one
  runner commit, `chore(<id>): share <name> (f<N>)`. It records the new HEAD
  for the checkout guard and tells the PO.
- The runner is the only writer of `shared:`. It rewrites only that block and
  refuses when the result would change any other key or the body.
- The hash is SHA-256 over the raw bytes, with no normalisation. It is unlike
  the s30 fingerprint, because a mock's whitespace is content.
- Acceptance checks every shared file's hash before the s95 round logic. A
  changed or missing file bounces the story to design. A malformed `shared:`
  list holds the story for the PO. Sharing again updates the recorded hash.
- The architect's and the Customer Proxy's briefs list the shared files. The
  design gate requires the design file to name each one. The Proxy's sandbox
  gains read access to exactly those paths.

## Consequences

- Every role reads shared files from where it already reads design docs. Only
  the Proxy's scope grows, and only by the story's own shared paths.
- A shared file is part of the team branch's history and reaches the review
  PR like any design doc.
- Roles are not blocked from editing a shared file, but an edit fails
  acceptance. The fix is to restore the shared version, or have the liaison
  share the new one.
- Shares are capped at 5 MiB each, because they are committed.
- No new dependency (stdlib `hashlib`, `base64`). `system` gains
  `write_bytes`.

## Amended by s133 (2026-10-14)

Design: `agile-team/docs/design/s133.md`. The s120 review found that a
hand-edited story or queue file could get past the checks (F2, F3, F4).

- **A shared path is resolved, then checked.** It passes only when it already
  is its own resolved form (no `.`, `..`, link or absolute part) and its parent
  is `<docs>/design`. Any other path is a `shared:` problem. Only the paths
  that pass reach the Proxy's scope and sandbox, the briefs and the hash
  check. This is stricter than "resolves inside the folder": a link that
  stays inside the folder is refused too, because the runner never writes
  one, and refusing it means the listed path and the read path are the same.
- **A request file is typed on load.** `Share.from_json` gives a `Share` or a
  `BadRequest` with its reason, and never `None`. A bad request is settled
  once as `refused: <reason>`, with one `share` event and no write. It used
  to be skipped silently on every tick, or to raise in the router.
- **The story id is passed in.** The brief section gets its story from its
  caller (`Brief(story, role)`). It no longer works the id out from a file
  name.
