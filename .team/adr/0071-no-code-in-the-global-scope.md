# ADR-0071: No code in the global scope

## Context

The human found 300+ lines of top-level code in
`scripts/make_dashboard_fixture.py`, and several code reviews had missed it
(s56). s116 has since rewritten that script into definitions and a `main`.
The rule exists in no prompt and no check. The human wants it enforced in code,
probably through a reusable `house-rules` skill that is still being planned.
`.claude/` belongs to the human and is on the charter's "Do not touch" list.

## Decision

- A Python module or script holds only these at its top level: the module
  docstring (first statement), imports, `Assign`/`AnnAssign`, function and
  class definitions, and an `if __name__ == "__main__":` guard whose body
  calls one entry function (`main`, or `just_do_it` when `main` doesn't fit).
- For now the rule is stated in the code-reviewer's built-in role file
  (`## Checklist`) and in `docs/guidelines.md`. A unit test pins the
  fixture script alone.
- The tree-wide AST check (s56/AC2, AC3, REQ-049) is deferred to a follow-up
  story after the `house-rules` plan. No interim scanner gets built, so there
  aren't two of them.
- The team never edits `.claude/`. Rules for `.claude/CLAUDE.md` go to the
  liaison as exact text, and the liaison makes the edit for the human to
  review.

## Consequences

- Until the follow-up lands, only the code review catches a violation in
  files other than the fixture script.
- The follow-up story must take over REQ-049's covers and may drop the
  single-file pin test in favour of the general check.
- A design whose story asks for a `.claude/` change hands the text to the
  liaison through the PO. The `.claude/` part of acceptance waits on the
  liaison and isn't a developer bounce.
