# ADR-0074: Event factory and naming rules

## Context

Most of the runner was written while the team's process was being
bootstrapped (s57), and it doesn't meet the house rules. Two problems show
this:

- `boundary_runner.boundary_event` builds an `Event` and emits it in one call.
  Other sites write `Event(EventKind.X, …)` inline, next to the emit, in about
  25 places.
- Names don't follow one style: noun-named functions (`boundary_data`), single
  letters (`b` for a boundary), alias locals (`rt = self.runtime`), and a
  `type: ignore` that hides the `Optional` `Runtime.upstream`.

The human set the rules on 2026-10-11. The runner has about 100 modules, too
many for one story.

## Decision

- **Event factory.** A new module, `agile_team/event_factory.py`, holds pure
  constructors, one per event kind: `build_<kind>_event(...) -> Event`. A
  constructor builds the event and never emits it, and it may take more than
  two parameters (factories are exempt). The caller emits the event with
  `EventLog.emit`. There is no helper that both builds and emits. s57 moves
  the boundary, PO-tool and recovery sites; follow-up Q1 moves the rest.
- **Verb rule.** Functions and methods are verbs. Only an accessor
  `@property` is a noun, and a plain getter is `get_<noun>`.
- **Whole words, no alias-only locals.** No single letters or
  abbreviations, except an acronym that is better known than its expansion.
  A local that only renames something is kept only when it makes the code
  much easier to read, and then it has a whole-word name.
- **Narrow, don't ignore.** `Runtime.remote` is a property that returns the
  upstream, or raises `RuntimeError` if it is missing. The field
  `Runtime.upstream` keeps its name and type, because tests construct it.
- These rules are a **judgement call for the code reviewer** (its
  `## Checklist`, and `guidelines.md` "Names"). They are not an AST check.
- **Split by module.** s57 fixes the named sites. Ten follow-up stories
  (Q1 to Q10 in `docs/design/s57.md`) check the rest, one module group each.
  Tests are not renamed in a quality pass, so a name that a test uses keeps
  its name.

## Consequences

- An event's data shape lives in one function, which can be unit-tested
  without an event log.
- Call sites get a little longer: they build the event, then emit it.
  `BoundaryRunner` keeps two small methods, `_build_event` (a factory) and
  `_emit(event)`.
- Reviews can cite the rules by name. Because nothing enforces them
  automatically, a missed name is caught in review, not in CI.
- Until Q1 to Q10 land, the code mixes old and new styles. A reviewer flags
  old style only in code the step changed.
- Names that tests use (e.g. `live.interrupted_data`) stay noun-named until
  the human allows a test rename.
