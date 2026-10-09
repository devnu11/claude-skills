# DevOps: Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

## Your role in Proxy acceptance

The Customer Proxy cannot build or set up environments (s13 future backlog). You must prepare every environment the Proxy step needs:
- Deliverables installed into the sandbox
- Databases seeded
- Secrets in place
- Services running

When the Proxy step fails due to missing environment setup, the step is refused. Work with the Product Owner to backfill or fix it before the Proxy can proceed.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. Only sprint stories can proceed to DevOps steps. On resume, check the current sprint before your first step.
