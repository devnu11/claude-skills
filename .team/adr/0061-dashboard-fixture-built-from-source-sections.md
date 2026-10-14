# ADR-0061: The dashboard fixture is built from source sections

Story: s116. Design: `agile-team/docs/design/s116.md`.

## Context

`agile_team/dashboard/fixtures/snapshot.json` is the dashboard's contract.
`scripts/make_dashboard_fixture.py` was meant to produce it. In practice it
had a seeded random "fake run" that was never used once the fixture got an
`upstream` key (s29). It also had a "live tail" step (s44, s98, s101) that
read the existing fixture, dropped every event after `CURATED_END` and
regenerated `turns`, `heartbeat`, `health` and `tools`.

Later stories hand-edited the fixture: curated events after `CURATED_END`,
new fields on the live events, and a version 2 heartbeat with `stages`. A
rebuild would have dropped or reverted all of them, so in s114 the team had
to hand-edit the fixture again (s114 review, D1). The fixture can't be
rebuilt, and nothing catches drift.

## Decision

- The fixture's source is plain data: one JSON file per top-level key in
  `agile-team/runner/scripts/dashboard_fixture/<key>.json`.
- The script's `SECTIONS` tuple fixes the key order, and the source directory
  must hold exactly those files. Otherwise the build fails and writes nothing.
- The script never reads `snapshot.json`. It has no randomness and no time
  filter. Output is `json.dumps(snapshot, indent=1)` with no trailing
  newline.
- The random generator, `CURATED_END` and the live-tail generators are
  deleted. No section is computed from code.
- An e2e test fails when the committed fixture differs from a fresh rebuild.
- The rule for everyone: edit the section file, rebuild, and never hand-edit
  `snapshot.json`.

## Consequences

- A rebuild can't lose curated content, and drift fails the suite.
- Derived values, such as the heartbeat's token sums over `turns`, are no
  longer computed. Whoever edits `turns.json` keeps `heartbeat.json`
  consistent by hand. We judged that cheaper than keeping generators in step
  with a curated fixture.
- A story that adds a top-level snapshot key adds `<key>.json` and the name
  in `SECTIONS`. The build refuses to run until it does both.
- The source is about as long as the fixture (23 files), but each file is
  small enough to edit and review on its own.
- No new dependency (stdlib only).
