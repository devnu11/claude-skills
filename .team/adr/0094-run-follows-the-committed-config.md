# ADR-0094: The run follows the committed config at a safe point

Story: s173. Design: `agile-team/docs/design/s173.md` (R1 to R10).

## Context

The runner read `.agile-team.toml` once at start, and the `Runtime` kept
that `Config` and everything built from it (pipeline, role book,
providers, command shell) for the whole run. A DevOps commit that added an
acceptance environment or changed a gate command did nothing until the
liaison stopped the team and resumed it. In sprint 51 that happened three
times in one day. Each restart moved the sprint head, cost a landing its
merge, and pruned story worktrees.

The options were: watch the file on disk, reload after each of the runner's
own commits, or compare the committed blob at a single safe point.

## Decision

1. **Committed content, not the working tree.** The run's config is the
   `.agile-team.toml` blob at the main checkout's `HEAD`. An uncommitted
   edit, or a story branch's edit before it lands, never reaches the run.
2. **One check, at the scheduler's safe point.** The check runs each tick,
   when the request queues may apply (main lock free, no boundary stage),
   and once right after a step's report. Comparing blob ids is one
   `git rev-parse`, so the check costs little. Blob ids don't change when a
   commit is rewritten (a landing carry, ADR-0093), so a rewrite triggers
   nothing.
3. **Swap by assignment.** A taken config replaces the runtime's `config`,
   `book`, `pipeline`, `providers`, `shell` (and `upstream`, when that
   section changed) with new objects. Story views keep references to the
   old objects, so a running step and its gate keep their config with no
   extra locking.
4. **A bad config is refused once.** A config that fails to parse or
   validate leaves the live parts as they were, logs one `config` event with
   the error, and gives the PO a non-holding `config_invalid` hand-over. It
   is in the committing step's report when that step's commit made it.
5. **Some keys stay start-only:** `[team] auth`, `key_file`, `cadence` and
   `[health] beat_s`. Rebuilding the key environment or the heartbeat in a
   running run would need far more care than the case is worth.

## Consequences

- DevOps config work is usable in the same run. The liaison no longer
  restarts the team for it, so the head moves and worktree prunes that came
  with each restart are gone.
- A runtime built without the CLI (tests) validates with its own book and
  keeps its providers and shell. Only the CLI's builder re-reads role files.
- The dashboard and the CLI commands still read the working-tree file, as
  before. Between an edit and its commit they can show a config the run
  doesn't use yet.
- A landing that waits on CI reads the live config, so a change committed
  during its wait applies to its later stages.
