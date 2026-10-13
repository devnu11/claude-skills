# ADR-0046: Story dependencies as data

**Decision:** Story dependencies are recorded as a `depends_on` list of story ids in each story file's YAML frontmatter. The list is loaded and validated on each start, checked on every step, skipped if waiting, and shown on the Backlog tab with warnings when misordered. Prose "Depends on sN" sentences are migrated to the data format.

**Date:** 2026-10-13  
**Status:** Accepted  
**Affected:** Developer, Unit Tester, Code Reviewer, Product Owner, Architect, Integration Tester, Customer Proxy

## Context

Dependencies between stories were expressed informally in prose in story files ("Depends on s1 for requirements"). This made it hard for the runner to enforce ordering and for the PO to see what blocked what. The dashboard Backlog tab (s83) needed to show and enforce dependencies visually.

The challenge is to record dependencies as data, validate them as a graph (no cycles, no self-references, no unknown ids), prevent starting a story until its dependencies are done, and warn when the human reorders the backlog in a way that puts a story above one it depends on.

## Decision

### Rules: dependency data structure and validation

| # | Rule | AC |
|---|---|---|
| DP1 | **Field.** A story file's YAML frontmatter may have `depends_on`, a list of story ids. A missing key means `[]`. `StoryState` gains `depends_on: list[str]` (default `[]`). Duplicates are dropped, keeping first (`dict.fromkeys`). | AC1 |
| DP2 | **The file wins.** For every open story whose file exists, a load sets `depends_on` from the file. Done stories are never reloaded. A story with no file keeps its state list. | AC1 |
| DP3 | **Load points.** (1) `cmd_start`, after `make_runtime` and before `_run`. (2) `start_sprint`, after existing refusals pass and before `_begin_sprint`. (3) `open_story`, for the new story only. No other code reads the files. | AC1, AC4 |
| DP4 | **Validation.** In order: shape (not a list of strings → `NOT_A_LIST`), self-reference (story lists itself → `SELF`), unknown id (not in state → `UNKNOWN`), cycle (graph has a cycle → `CYCLE`). Done stories are known; dependency on a done story is satisfied. First refusal wins. | AC1 |
| DP5 | **Refused means unchanged.** On refusal, no list changes and nothing is saved. `cmd_start` raises `CliError(START_REFUSED…)`, run does not start. `start_sprint` returns `refused()`, sprint does not begin. On success all lists are applied and state saved. | AC1 |
| DP6 | **`open_story` accepts `depends_on`** (a list). After duplicate-id and delivery checks: the argument is not a list of strings → `NOT_A_LIST`. The story's file exists but has a different list → `MISMATCH` (order-sensitive, after dedup). Then DP4 (b)–(d) on the new graph including the new story. On success the story is opened with the list, and the event data gains `"depends_on"`. | AC1, AC4 |
| DP7 | **Cycle text is deterministic.** Walk depth-first from each story id in `priority.natural` order, following each list in its own order and skipping unknown ids. On the first time a step reaches an id already on the current path, the cycle is `path + id`, e.g. `s1 -> s2 -> s3 -> s1`. | AC1 |
| DP8 | **Waiting.** `waiting_on(story, stories)` returns the story's listed ids, in list order, whose story is missing or not `DONE`. | AC2 |
| DP9 | **Routing.** `Router._movable` adds a check: `not dependencies.waiting_on(story, rt.state.stories)`. A dependency added mid-sprint stops the story too. The PO's own `run_role` is not checked. | AC2 |
| DP10 | **Skip reason.** `_why` becomes `_why(story, stories)`: a hold first, then `WAITING` when `waiting_on` is non-empty, then status texts. Stalled hand-over reads e.g. `s2 at design: waiting on s1`. | AC2 |
| DP11 | **Inversion.** In a queue, story `A` is above a dependency `D` when `D` is in `A.depends_on` and `D` comes after `A`. `above(story, queue)` lists those `D` in list order. | AC3 |
| DP12 | **Moves are never refused.** `Runtime.reorder` adds `"warnings"` to every `priority` event's data: `WARNING` texts for each inversion new to `after`. `[]` when none. Other data keys are unchanged. | AC3 |
| DP13 | **Snapshot.** Each story gains `depends_on` (state list), `waiting_on` (DP8, `[]` if done), and `dependency_warnings` (DP13: `WARNING` per `above` id, `[]` if done). | AC3 |
| DP14 | **Backlog tab.** Non-empty `depends_on` shows `depends on s1, s2 (done)`. An id not in `waiting_on` gets ` (done)`. Each warning shows as `⚠ <text>`. Both Current sprint and Backlog groups show them. A `priority` event with warnings appends ` · ⚠ <w1>; <w2>` to meta and takes tone `warning`. | AC3 |
| DP15 | **Migration.** For each open story with prose "Depends on sN", set frontmatter `depends_on` to the list and delete the sentence. Reasons stay as YAML comments on items. Done dependencies are dropped. Drop-done examples: s2 `[s1]`, s6 `[s1, s2]`, s10 `[]`, s39 `[]` (s29 done). | AC4 |
| DP16 | **Migration pin.** An e2e test reads real `.team/stories/*.md` bodies. Every file matching `(?i)\bdepends\s+on\s+s\d+` must be in `HISTORY` (done stories). Each table-M story's declared list must equal the table. | AC4, AC5 |

### Texts (tests may assert them exactly)

- `NOT_A_LIST = "depends_on must be a list of story ids: {ids}"`
- `SELF = "a story cannot depend on itself: {ids}"`
- `UNKNOWN = "depends_on names unknown stories: {pairs}; open them with open_story first"` (pairs `"{story} on {dep}"`)
- `CYCLE = "depends_on has a cycle: {cycle}"`
- `MISMATCH = "{story}'s file has depends_on [{file}], not [{given}]; pass the same list, or fix the file"`
- `WAITING = "waiting on {ids}"` (list order)
- `WARNING = "{story} is above {dependency}, which it depends on"`
- `START_REFUSED = "story files: {refusal}; fix depends_on in {folder}"`

### Modules and changes

**New:** `agile_team/dependencies.py` (350 LOC)
- Type `Graph = dict[str, list[str]]`
- Dataclasses: `Declared` (lists, bad), `Proposal` (story, deps), `Moved` (before, after)
- Functions: `listed` (dedupe), `open_ids`, `declared` (read files), `graph_of`, `merged`, `shape_refusal`, `mismatch_refusal`, `find_cycle` (DP7), `graph_refusal`, `load_refusal`, `apply`, `waiting_on` (DP8), `above` (DP11), `inversions`, `warnings` (DP12), `warning_texts` (DP13)

**Changed:**
- `gates.py`: `StoryState` gains `depends_on: list[str] = field(default_factory=list)`
- `dispatch.py` (`Runtime`): `load_dependencies()` method (DP2–DP5); `reorder()` adds `warnings` to event data (DP12)
- `cli.py`: `_load_dependencies()` function calls `runtime.load_dependencies()` after `make_runtime` (DP3); `START_REFUSED` text
- `router.py`: `_movable` adds `and not dependencies.waiting_on(story, rt.state.stories)` (DP9); `_why` becomes `_why(story, stories)` (DP10)
- `po_tools.py`: `_open_refusal` adds `_depends_refusal` check (DP6); `open_story` accepts `depends_on` and adds it to event data; `start_sprint` calls `load_dependencies()` (DP3); `SCHEMAS` updated
- `dashboard/snapshot.py`: `_story` adds three keys (DP13)
- `dashboard/index.html`: helpers `depsLine`, `depWarnings`; `backlogRow` shows them; `TIMELINE.priority` shows warnings in meta and tone
- `roles/product-owner.md`: step 2 adds guidance on `depends_on` in frontmatter and `open_story` argument

**Updated docs:** `agile-team/reference/protocol.md` (load points, validation, routing, snapshot), `agile-team/docs/customer/dashboard.md` (Backlog row), `agile-team/SKILL.md` (step 6)

## Consequences

**Positive:**
- **Dependencies are visible and enforced.** The router won't start a story until its dependencies are done. The PO and human can see what blocks each story.
- **Ordering is protected.** The Backlog tab warns (not refuses) when the human puts a story above one it depends on. The warning is recorded in the timeline.
- **Validation catches mistakes early.** Cycles, self-references, and unknown ids are refused at start or `start_sprint`, with clear messages naming the stories.
- **Prose is gone.** No more `"Depends on s1 (…)"` sentences. Data is canonical, consistent, and machine-readable.

**Tradeoffs:**
- **No undo of dependency edits mid-sprint.** An edit to a file's `depends_on` takes effect at the next start or `start_sprint`, not immediately. The snapshot shows the state list.
- **Circular dependencies stall forever.** A dependency on a held (cancelled) story waits forever. The PO must edit the file.
- **No dependency in the Stories tab.** The s40 `wait` reason (Stories tab) doesn't include dependencies. `waiting_on` covers Backlog and stall line.
- **null and bare : are not `[]`.** `depends_on: null` or `depends_on:` (nothing after) are `NOT_A_LIST`, not `[]`. Non-UTF-8 story files raise out of `system.read_text` and are not refused (DP4a as written).

**Future:**
- **Forward-chaining.** When a story is marked done, dependents waiting on it could be auto-unlocked (s86 design DP2 comment: "a dependency added later stops a started story too" means reversal is possible).

## Related decisions

- **ADR-0043 (s83):** Backlog reorder—this decision integrates with the backlog display (B1) and human reorder requests (B12–B17). Warnings are emitted on reorder.
- **ADR-0027 (s4):** Snapshot raw data contract—this decision adds three keys per story; builders are ≤8 lines.
- **ADR-0016 (s51):** Story priority ranking—this decision adds a waiting check to `Router._movable` (which calls `priority.natural` in `graph_refusal`).

## Notes

**Migration is complete (DP15):** All open stories that had prose dependencies now have `depends_on` in frontmatter. Done-only dependencies (s29 → s39, etc.) were dropped as DP15 specifies. The migration test (DP16) will check that no prose remains outside `HISTORY`.

**s39 confirmed:** AC4's table lists "s39 on s29", but s29 is done, so DP15's drop-done rule removes it. s39 has no `depends_on` entry; the file reads as `[]`. Confirmed by the PO.

**Open question (integration-tester, P1):** DP16 pin and page harness tests (node-harness) for AC4 and AC5.
