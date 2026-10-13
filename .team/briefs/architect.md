# Architect brief

**s114 done:** Scribe retired. You own ADRs; write them at design (`.team/adr/NNNN-<slug>.md`, context/decision/consequences), numbered one above the highest, not after the fact. When a decision changes, amend the existing ADR (dated "Amended by sN" section) instead of writing a contradicting one. Your write scope is now `["{docs}", ".team/adr/**"]`.

**Conventions:** ADRs live in `.team/adr/` and are owned entirely by you. No role writes briefs anymore; prompts show the story, design, ADRs and code only.

**Pitfall:** Repos that override your write scope must add `.team/adr/**` to their `.agile-team.toml` or you cannot write ADRs there.
