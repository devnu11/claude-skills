# Integration Tester brief

**s114 done:** Scribe retired. Step sequences no longer end with `scribe`; done stories queue no further work. E2E case: an old state with `scribe_due` and `.team/briefs/` loads, runs to done with no Scribe step, saves with no `scribe_due`. A repo with `[roles.scribe]` makes `start` exit 1 with refusal message.

**Conventions:** Replace Scribe steps in routing tests with `quality-czar` if needed for storyless sampling.

**Pitfall:** Ledger lines naming `scribe` as history may stay (old data); only forward routing and new steps have no Scribe.
