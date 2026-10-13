# Unit Tester brief

**s114 done:** Scribe and briefs retired. Key tests:
- `test_roles.py`: Architect write scope is `["{docs}", ".team/adr/**"]`; system prompts have no `Brief from the Scribe` section.
- `test_state.py`: `scribe_due` is dropped on load; `to_json()` has no `scribe_due` key.
- `test_config.py`: `[roles.scribe]` raises `ConfigError` with exact refusal message.
- `test_roles.py`: Non-stub `.team/roles/scribe.md` raises `RoleError`; stubs are ignored.
- `test_cli.py`: `RoleError` on a non-stub scribe file prints as one-line refusal, not traceback.
- `test_gates.py`, `test_dispatch.py`: `UNGATED_ROLES = {"manager"}` only; done story queues nothing.

**Conventions:** Retired role refusal texts are pinned exactly in tests. No `scribe` sample roles; use `quality-czar` instead.

**Pitfall:** Regex `(?i)scribe` matches "describe" and "prescribe"; use `\bscribe\b` to avoid false positives on future role file changes.
