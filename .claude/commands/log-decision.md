---
description: Append a phase entry to docs/ai-workflow-log.md
argument-hint: <phase> — <one-line summary>
---

Append an entry to `docs/ai-workflow-log.md` for: $ARGUMENTS

Use the file's existing four-field shape, and fill it from what actually happened in this session
rather than from a plausible-sounding reconstruction:

- **Asked for** — what I directed Claude Code to do
- **Produced** — what it generated
- **Changed** — what I corrected, rejected, or rewrote, **and why**. If nothing needed changing, say
  that; a log of only smooth successes is a log nobody will trust.
- **Verified** — how it was confirmed to work, with real numbers or commands

Keep it terse. The narrative belongs in `reports/phase-<n>-report.md`, not here.
