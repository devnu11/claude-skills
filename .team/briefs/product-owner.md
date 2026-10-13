# Product Owner brief

**s114 done:** Scribe role retired. A done story queues nothing; no brief is written after each story. No `.team/briefs/` directory exists; roles read the story, design, ADRs and code directly. The Architect writes ADRs at design; see ADR-0050 for retirement consequences.

**Conventions:** Stories cost one fewer step. When you need to give a role context beyond the story file (e.g., a design decision or convention), write it in the design file or ask the architect to write an ADR, not a brief.

**Pitfall:** Old `.agile-team.toml` files with `[roles.scribe]` or old repos with `.team/roles/scribe.md` must remove them before their next start, or the runner refuses.
