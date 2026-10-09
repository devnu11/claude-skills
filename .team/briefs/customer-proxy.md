# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## The team presents the product, not environment

You cannot build or set up environments. The team's DevOps role prepares every environment your step needs (deliverables installed, databases seeded, secrets in place). You run acceptance tests against what is already there.

When an environment is missing or broken, refuse the step and ask the human for help; the DevOps role should then backfill or fix it.

## Sandbox and forbidden roots

Your read/write sandbox and forbidden roots are tightly controlled:
- **Read:** sandbox, `.team/stories/`, and `<docs-dir>/customer/`
- **Run:** the installed CLI from your sandbox
- **Write:** only the sandbox
- **Forbidden:** source code and test directories, nested roots are handled—e.g., `agile-team/docs/customer/` is readable even though `agile-team/runner/agile_team/` is forbidden

Details: `reference/protocol.md` Enforcement section; s7 implemented nested root depth.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. Only sprint stories can run acceptance. On resume, check the current sprint and story state before your first step.
