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
