# Scribe: Current context and conventions

**Last updated:** 2026-10-11 (s4 documented, s45 done)

## Your mission: record decisions and refresh briefs

After each completed story, create an ADR and refresh affected role briefs (under 30 lines each, no append). Recent stories and their ADRs:

- **s4 (done):** Dashboard backend - snapshot builder, read-only SSE server, CLI. Raw data contract: Python builds snapshot, browser derives views. Pure snapshot building, no aggregation in Python, exact server routes, file watching SSE. **ADR-0027.** Affects: developer-cli, unit-tester, code-reviewer, product-owner, architect, customer-proxy.
- **s45 (done):** Manager crash fixed; crash log captures tracebacks; fault rulings work on any story; blocked release blocked. **ADR-0023.** Affects: developer-cli, unit-tester, manager, product-owner, architect, customer-proxy.
- **s38 (done):** Budget numbers and ceiling - status, dashboard and the budget check use the corrected ledger, and the ceiling halts the run. **ADR-007.** Affects: developer-cli, unit-tester, code-reviewer, product-owner, architect, manager.
- **s37 (done):** Unattended wake time and reason sources. **ADR-0020.** Affects: developer-cli, unit-tester, code-reviewer, product-owner, architect.
- **s29 (done):** Sync with upstream and deliver stacked PRs. **ADR-0015.** Affects: developer-cli, unit-tester, product-owner, manager, devops, architect, code-reviewer.
- **s27 (done):** Escalate repeated setbacks to the Manager. **ADR-0014.** Affects: developer-cli, unit-tester, product-owner, manager, architect, code-reviewer.
- **s26 (done):** Liveness is data, absolute paths, service lifecycle. **ADR-0013.** Affects: developer-cli, integration-tester, customer-proxy, product-owner, unit-tester, architect, devops.
- **s25 (done):** Cost delta tracking via SessionCost. ADR-004 (one-off correction: $256.93 for old PO entries).
- **s24 (done):** Rework gate and hold clearing. **ADR-0012.** Affects: developer-cli, unit-tester.
- **s23 (done):** Cost reduction via session renewal and context isolation. **ADR-0010, ADR-0011.** Affects: product-owner, unit-tester, architect, manager, developer-cli.

Earlier: s5, s8, s13, s19 (ADRs 0002–0009); s3, s7 (documented).

## Routing and automation (s19)

The runner drives the pipeline automatically; the PO judges only. Scribe runs after each `DONE` story.
