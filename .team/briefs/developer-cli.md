# Developer (CLI) brief

**s114 done:** Scribe and briefs retired from the runner. Changes:
- `roles.RETIRED_ROLES` dict + `retired_sections()` + `retired_files()` functions check for retired roles on load.
- `roles.system_prompt` no longer reads `.team/briefs/`; `roles.BRIEFS` is deleted.
- `RunState.scribe_due` and `state.RUN_DROPPED` drop stale `scribe_due` from old state files.
- `dispatch`, `router`, `gates` have no Scribe picker, routing or queue; `UNGATED_ROLES = {"manager"}` only.
- `cli.main` catches `RoleError` and prints it as a one-line refusal, not a traceback.

**Conventions:** Retired role detection is data-driven: add role name and reason to `RETIRED_ROLES`, functions use it. Config and state reject it; RoleBook ignores stubs.

**Pitfall:** Keep old event logs and `interrupted` records that name `scribe`; they still render. Only forward-facing code (routing, prompts, new tests) has no Scribe.
