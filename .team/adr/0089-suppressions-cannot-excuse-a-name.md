# ADR-0089: A suppression can't excuse a name; designs name things by the house rules

Story: s161. Design: `agile-team/docs/design/s161.md` (N1 to N6, Q1 to Q3,
E1 to E5, D1 to D3). Amends ADR-0074 (the naming rules are a check now, and
tests follow a rename).

## Context

s157 put house-rules into the team's toolchain, so `verb-name` and
`query-property` became checks. s159 and s163 then added 43
`# house-rules: allow` comments with reasons such as "name fixed by the s159
tests" or "s163 design name". The designs named the functions, the tests
used the names, and the developer waived the rule rather than send the names
back. house-rules reads only Python, so nothing held a design to the rules.
The `suppression-reason` rule only asked that some reason be given. The
human: "tester doesn't get to name things, the architect does."

Some of the methods were commands that change state, but the query-property
heuristic couldn't see the change. It saw neither a tuple assignment
(`queued, self._queue = …`) nor a change made by another method of the same
class. Renaming those methods would not clear the finding, and the
alternative was another suppression.

## Decision

1. **Rename, don't waive.** Every function those comments covered is
   renamed to pass. A query becomes a property, and a real English verb
   missing from house-rules' table goes into the repo's `.house-rules.toml`
   `verbs`. The PO tool `order_landings` keeps its name through
   `po_tools.METHODS`.
2. **A new rule, `suppression-excuse`** (fail), refuses a suppression whose
   reason, cut at a chained `#`, fully matches an excuse pattern: tests, a
   test file or a design fixed the name. The defaults live in
   `house_rules.config.DEFAULT_EXCUSES`, and a repo extends them with the
   `excuses` key. One finding per file, like `suppression-reason`. A
   separate rule, rather than a stricter `suppression-reason`, keeps one
   check per rule, and lets a repo disable or relax it without losing the
   reason check.
3. **The query heuristic gets two fixes:** it unpacks tuple and list targets,
   and it treats a call on `self` to a method of the same class that changes
   `self` as a change, repeated until nothing more is added. Both only
   remove false findings.
4. **Names start at the design.** The architect names everything by the
   house rules. A developer or unit-tester who meets a design name the
   rules refuse hands off `changes_requested` with `next_role: architect`
   (the existing bounce) instead of renaming it or suppressing the rule.

## Consequences

- No new excuse suppression can land. The static check and every done stop
  run house-rules over the repo (ADR-0081).
- A heuristic miss still allows a suppression, with a reason that says what
  the heuristic gets wrong.
- The `verbs` list grows only with real verbs. Each addition is a repo
  decision, made in a story's design.
- Findings that the heuristic fixes remove leave stale baseline entries.
  The toolchain's fix command (`house-rules baseline`) drops them, so the
  baseline only shrinks (REQ-113).
- The rename touches many test files once. After this story, a rename the
  rules ask for goes through design, not through a waiver.
