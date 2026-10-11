<!--
unit-tester: your instructions for this role (repo layer).

Write plain Markdown below this comment; it is appended to the role's
built-in prompt. Layers apply in order: built-in, then global
(~/.config/agile-team/roles/, or $AGILE_TEAM_HOME/roles/), then this repo
(.team/roles/). To replace the role entirely, start the file with YAML
frontmatter (---) instead. _shared.md applies to every role.
This comment is ignored.

Role: Writes unit tests first and proves they fail before implementation.
-->

## Time, waits and sleeps are mocked

Tests never wait on real time. Any code that sleeps, polls, waits for an
answer or checks a deadline gets its clock, sleep or wait function injected,
and the test passes a fake that returns at once or advances a fake clock.
A wait the design calls "indefinite" is tested by checking the decision to
wait, not by waiting. We don't need to wait 10 minutes when 0.1 s (or no
time at all) proves the same behaviour.

If a test needs a real timer at all, keep it to a fraction of a second and
give it a hard timeout, so a mistake fails fast instead of hanging the suite.
