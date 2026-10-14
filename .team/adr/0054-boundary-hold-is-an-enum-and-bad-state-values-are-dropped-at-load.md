# ADR-0054: A boundary hold is always a `BoundaryHold`; a bad stored value is dropped at load with a fault

Story: s123. Design: `agile-team/docs/design/s123.md`.

## Context

`BoundaryRunner.after_fix` set `boundary.hold` to `handover.hold_reason(report)`.
That is the trigger names joined by ", " (for example `"stopped, questions"`),
a story-hold format, not a `BoundaryHold` value. The running runner kept the
string in memory, but every later load of `state.json` failed in
`Boundary.__post_init__` (`ValueError: ... is not a valid BoundaryHold`). So
`agile-team watch`, `status` and a resume all crashed on one bad field.

The s29 design (U11) and `protocol.md` intend that "a fix step that hands
over holds the boundary": the boundary should not rerun its stage while the
PO is handling the fix's questions or blocker. The hold is right. Its value
was wrong.

## Decision

1. **A fix that hands over holds `fix_handover`.** `BoundaryHold` gains
   `FIX_HANDOVER = "fix_handover"`. `after_fix` sets it when
   `handover.triggers(report)` is not empty and sets `None` otherwise. The
   triggers reach the PO through the router's normal handover (`Router._step`),
   as they do for any step. `continue_boundary` releases the hold, and the
   stall line's hint says so.
2. **A stored hold that is not a `BoundaryHold` value is dropped at load.**
   `state.from_json` keeps the hold only if it is a known value. Otherwise it
   loads `None` and adds a `LoadFault(field, value, reason)` to the new
   persisted list `RunState.load_faults`. Loading never raises for this field.
   Read-only readers (`watch`, `status`, the dashboard) just see no hold.
3. **The runner reports each load fault once.** `cmd_start` calls
   `Runtime.report_load_faults()` after it builds the runtime. That method
   emits one run-level `fault` event per entry
   (`{"fault": "state", "field", "value", "reason"}`), empties the list and
   saves. The list is persisted so that an earlier save at start
   (recovery, checkout guard) cannot lose the fault before the runtime
   reports it.

## Consequences

- `boundary.hold` is a `BoundaryHold` or `None` both in memory and on disk.
  Story holds (`StoryState.hold`) keep the joined-trigger text. They are a
  separate field with a separate format.
- `state.json` has a new top-level key `load_faults` (a list, normally empty).
- Only the boundary hold is validated this way. A new enum field that could
  hold bad stored values should follow the same pattern: drop it, record a
  `LoadFault` and report it at start. Do not let the whole load fail.
- A `fault` event can now have no story and `fault: "state"`. Consumers that
  read `fault` events (story history keyed by story) skip it.
