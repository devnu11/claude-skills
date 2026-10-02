---
name: example-skill
description: Template showing the skill file format. Replace or delete this directory. Claude matches this description text to decide when a skill applies, so real skills should name concrete trigger phrases here, e.g. "use when the user asks to cut a release, tag a version, or write release notes".
---

# Example skill

This directory exists to show the layout. Delete it once there are real skills.

## Structure

The frontmatter above is the only required part. `name` should match the
directory name; `description` is the trigger text Claude matches against.

Everything below the frontmatter is the instruction body, loaded into context
when the skill fires. Keep it short and concrete — steps, not background.

## Supporting files

Large reference material belongs in a separate file next to this one, pointed
at by path rather than pasted inline:

> For the full field list, read `reference.md` in this skill's directory.

That keeps the skill cheap to load and lets Claude pull in detail only when it
actually needs it.
