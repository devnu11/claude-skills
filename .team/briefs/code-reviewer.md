# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Design decisions to verify

**Over-approximation in security (s7):** The Proxy Bash enforcement denies on any plausible view of a command (shell or comment interpretation). Review that this over-deny does not break legitimate workflows; ask the Customer Proxy to rephrase if it does.

**Backlog gating (s3):** Ensure the `_story_refusal` check is working: story-bound steps must refuse on backlog stories with a clear message.

**Test expectations (via Unit Tester):** The Unit Tester re-reads every test against the design. You are a secondary check for misalignments between code and tests.
