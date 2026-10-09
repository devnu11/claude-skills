# ADR-0001: Deny on any view for Proxy Bash token check

**Date:** 2026-10-09  
**Status:** Accepted  
**Affected:** Customer Proxy Bash enforcement (s7)

## Context

The Customer Proxy enforces Bash word checks to prevent access to forbidden roots (source, tests, e2e directories). Commands may span multiple lines with `\` continuation, and comments (starting with `#`) end the line.

To handle these correctly without fully parsing shell grammar, the enforcement checks commands in two views:
1. Shell view: continuations joined like bash/zsh do
2. Comment view: continuations joined except on lines holding `#`

The word token check runs on each view independently, including path and forbidden-root matching.

## Decision

When a Bash command is checked against multiple views, **deny the command if any single view produces a denial**. This is an over-approximation: a quoted `#` in a literal string can cause spurious denial in the comment view.

Over-denying is acceptable because:
- Modelling full shell grammar in a hook is costly and error-prone
- False negatives (allowing forbidden access) are dangerous
- False positives (denying safe commands) are inconvenient but not unsafe
- Customers can work around with unambiguous quoting or alternative phrasing

## Consequences

- **Safe:** No command that could access forbidden roots will execute
- **Predictable:** Customers understand "any view" = "any interpretation"
- **Maintainable:** Enforcement stays simple and auditable without a parser
- **Trade-off:** Some safe commands with quoted comments may be denied (rare in practice)

## Implementation

Enforcement section in `reference/protocol.md` documents this precisely: "a denial in any view denies the command. A quoted `#` can over-deny, but no view under-denies."
