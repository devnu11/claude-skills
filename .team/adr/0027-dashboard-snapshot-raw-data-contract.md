# ADR-0027: Dashboard snapshot as raw data contract

**Decision:** The snapshot builder (`snapshot.py`) returns raw, unaggregated data directly from run files. The UI (`index.html`) derives all views (board, flow, tokens, questions) in the browser from this raw data. The fixture (`snapshot.json`) is the API contract, not the views.

**Date:** 2026-10-11

## Context

The dashboard must display the team's work in progress: stories, events, costs, messages, and requirements. A straightforward approach would aggregate and format everything in Python before sending it to the browser. However, this would couple the server to the UI's needs and require server changes whenever a view changes.

An alternative is to send only the raw data the UI needs, and let the browser assemble the views. This separates concerns: the server focuses on reading files correctly and building a canonical snapshot; the UI focuses on presenting that data clearly.

## Decision

### Rules

| # | Rule | AC |
|---|---|---|
| S1 | **The fixture is the contract (AC3).** `snapshot.json` defines the structure. `build(config, book) -> dict` returns exactly those eleven keys in that order: `generated_at, run, pipeline, roles, stories, requirements, events, ledger, messages, answers, upstream`. After a JSON round trip, value types match the fixture. | AC1, AC3 |
| S2 | **Pure data building (AC4).** `build()` only reads files: `state.json`, `ledger.jsonl`, `events.jsonl`, `outbox.jsonl`, `inbox.jsonl`, story frontmatter, and requirement files. It never writes, never runs git, never touches the network. The only side effect is `time.time()` for `generated_at`. | AC1, AC4 |
| S3 | **No aggregation in Python (AC1, AC2).** Views are derived in the browser: board columns, flow stats, event timeline, token totals, requirement coverage. Each view reads one or more snapshot keys and computes what it needs in JavaScript. | AC1, AC2 |
| S4 | **Missing files are empty (AC1).** A missing file or directory gives an empty section (`[]` for arrays, `{}` for objects) or the section's default (e.g., `RunState()` for `run`). A blank or malformed JSONL line is skipped. Torn lines at the end are normal because the runner appends while the server reads. | AC1 |
| S5 | **Server routes are exact (AC4).** Only three routes: `GET /` → `index.html` from package data, `GET /api/snapshot` → snapshot JSON, `GET /api/stream` → SSE. Any other path is 404. No file path is built from the request; every route is a literal lookup. | AC4 |
| S6 | **SSE with file watching (AC4).** Each tick computes a fingerprint of all watched files (mtimes and sizes). On the first tick and whenever the fingerprint changes, send the snapshot. Otherwise send a keepalive comment. Sleep 1 second between ticks (configurable). End the stream on socket errors. | AC4 |
| S7 | **CLI picks a host and port (AC5, AC6).** `default_host()` returns `0.0.0.0` (all interfaces) except on Windows (`127.0.0.1`). `--host` overrides. When bound to all interfaces, the printed URL uses the machine's hostname so it can be opened from another machine. `--port 0` picks a free port and prints the actual bound port. `--no-open` skips the browser. | AC5, AC6 |

### Implementation approach

- **`dashboard/snapshot.py`:** `build(config, book)` reads and assembles each section from `RunFiles`. Each section builder is 8 lines or fewer, reads only its source files, and returns the raw data (arrays of dicts, or objects).
- **`dashboard/server.py`:** `Dashboard.for_run()` ties snapshot building and file watching to one run. `Handler.do_GET()` routes exact paths and calls builders. `_stream()` watches files and sends SSE. No caching; every client gets a fresh snapshot on connect.
- **`cli.py`:** `cmd_dashboard()` binds, prints the URL, opens the browser (unless `--no-open`), and serves. Uses stdlib `ThreadingHTTPServer` and `webbrowser` module.
- **`index.html` (s5):** Reads the snapshot and renders views via `renderBoard`, `flowStats`, `coverage`, etc. Each view is independent and recomputes when the snapshot changes.

### Why this design

**Loose coupling:** The server doesn't know about boards, tokens, or questions. The UI doesn't know about how the snapshot is built. They meet at the JSON contract.

**No aggregation logic in the runner:** A story is a row in `stories[]; its board column is determined by `step` and `status`, which the UI can compute. A ledger entry is a row in `ledger[]`; cumulative cost is a sum the browser can do.

**UI can iterate freely:** Changing how the board looks, adding a new chart, or reordering the flow doesn't touch the server. The fixture version stays stable.

**Files are canonical:** The snapshot is never cached or computed incrementally. Every request to `/api/snapshot` is fresh. SSE polls files, not an in-memory cache, so a stale state can't drift from the truth.

**Testing is simple:** The fixture is an example snapshot. Tests check that `build()` matches its structure. The UI test the fixture against the mock UI in a browser test.

## Consequences

**Positive:**
- The server is stateless and pure. Every request is independent; file state is the only source of truth.
- The dashboard can be added to the runner without teaching the runner about UI views.
- The UI can evolve (new charts, reordering, styling) without server changes.
- SSE keeps clients live without polling the snapshot endpoint. File watching is transparent to the browser.
- No aggregation logic to test and maintain in Python.

**Tradeoffs:**
- The browser must do the work to render views. For a fast machine or small dataset this is fine; for very large event logs, a future optimization could ask the server to pre-compute timeline windows or token summaries.
- The snapshot JSON can be large (event log grows each step). The UI shows the last 120 events on the timeline, but the full log is sent.
- View-specific filtering (e.g., "show only stories in sprint 2") must be done in the browser, not at the API level.

**Future:**
- If the dashboard slows down with a large run, incremental snapshots (send only changed sections) could be added without breaking the contract.
- Requirements rendering (s1) and other new views will plug into the same snapshot keys.

## Amended by s121 (2026-10-13)

`run` gains `requirements_dir`: the repo-relative requirements directory,
`<docs_dir>/requirements` in POSIX form. `_run` computes it from the config
and does not read the disk. It is a raw config value, not a view. The page
needs it to name the real path in the empty Requirements tab, and the
browser can't derive it. S3 still holds: the Board's membership (current
sprint only) and its badge count are derived in the browser, not in Python.
See `agile-team/docs/design/s121.md` RQ1.

## Amended by s128 (2026-10-14)

`run` gains `runner_pin`: the full sha in `.team/run/runner-pin.commit`, or
`""` when the runner is not pinned. It is a raw file value. The header shows
`pin <sha7>` from it. See `agile-team/docs/design/s128.md` P12 and ADR-0065.

## References

- Story: `.team/stories/s4.md`
- Design: `agile-team/docs/architecture.md` § "s4: Dashboard backend"
- Review: `.team/reviews/s4.md`
- Fixture: `agile-team/dashboard/fixtures/snapshot.json`
