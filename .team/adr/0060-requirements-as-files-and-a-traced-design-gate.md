# 0060: Requirements as files, and a design gate that traces every AC

Story: s1.

## Context

Reviewers bounced stories because roles read the same AC differently. Nothing
durable said what the product does. The dashboard's Requirements tab read
`<docs>/requirements/REQ-*.md` loosely, and no such file existed. The human
asked (t80) for structured requirement files and for every new story's ACs to
be traced to one before implementation starts. Stories designed before this
change were never traced, and tracing ~120 old stories is not asked for.

## Decision

1. **Format.** A requirement is one file, `<docs>/requirements/REQ-NNN.md`
   (`REQ-` and three or more digits). YAML frontmatter
   `{id, title, status: active|retired, covers: ["sN/ACk", …]}` and a body that
   states the requirement in plain words. The file name is the id. One pure
   module, `agile_team/requirements.py`, parses and checks every file; its
   problem lines read `{file}: {problem}`, like `story_spec`.
2. **Coverage.** An AC `sN/ACk` is covered when a requirement whose file has
   no problem, with `status: active`, lists it in `covers`. One AC may be
   covered by several requirements; one requirement may cover ACs of many
   stories.
3. **The design gate.** A `done` handoff at `design` runs one gate
   (`Checks.designed`) that lists every reason at once: the s124 After revert
   section (when reverted) and, for a traced story, each AC with no covering
   requirement plus each problem of a requirement file that mentions the
   story (`sN/` in its text). A bounce stays at `design` (a round).
4. **Which stories are checked** is runner state, not a file a role can edit:
   `StoryState.trace` (`gates.Trace`: `checked` | `exempt`). A new
   `StoryState` is `checked`. A state saved before s1 has no key; it loads as
   `checked` only when the story is at `design` with no previous step (never
   designed), else `exempt`. No tool changes it.
5. **CLI.** `agile-team requirements check` prints one JSON object (problems,
   coverage of every readable story file, unreadable story files) and exits 1
   on problems. Untraced ACs are not problems: old stories stay untraced.
6. **Briefs, not a shell.** The architect has no shell, so the runner puts
   the story's coverage and the index of active requirements in the design
   brief. The code reviewer's and the Customer Proxy's briefs get the
   coverage, so they can cite REQ and AC ids.

## Consequences

- From s1 on, a story can't leave design with an untraced AC; the Manager's
  `advance` ruling stays the only override.
- The architect owns `<docs>/requirements/` (its write scope already holds
  `{docs}`). Change tracking of requirement edits (`requirement-changed`
  events, auto-accept, `requirements log`) is s2.
- A requirement file that breaks blocks only the stories it mentions, at their
  design gate; `requirements check` shows every problem repo-wide.
- No new dependency (PyYAML is already used for frontmatter).
- The dashboard's snapshot keeps its own lenient read of the files; its
  stories gain `trace` so pre-s1 stories are not shown as gaps.

## Amended by s143 (2026-10-15)

The AC part of a `covers` reference may contain dots. `requirements.REF` is
now `(s\d+)/([A-Za-z][\w.-]*)`: a story id `s` plus digits, a slash, then an
AC id that starts with a letter and goes on with letters, digits, `_`, `-`
or `.`. Why: s141 numbers its ACs `AC1.1` … `AC8.3`, story files never
restricted AC ids, and the old `[\w-]*` made those ACs untraceable, so the
design gate bounced them as `BAD_REF`. Every reference valid before stays
valid; the `BAD_REF` text (`is not "sN/ACk"`) is unchanged.
