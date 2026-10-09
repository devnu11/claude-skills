# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-09 (s7, s3)

See `developer.md` for the base conventions.

## CLI-specific context

**Nested sandbox roots (s7):** The Customer Proxy reads customer docs and uses the installed CLI. Ensure CLI help and examples don't reference source code paths. Keep documentation output friendly to restricted sandboxes.

**Bash enforcement (s7):** Design CLI output and examples to avoid quoted comments or ambiguous shell constructs. The Proxy's check is conservative; when it blocks a legitimate command, refactor the example or workflow.
