---
description: Re-scrape cadreai.com and propose corpus updates (never writes the corpus)
allowed-tools: Bash, Read, Grep, Glob, Task
---

Refresh the knowledge-base corpus from the live site and report what changed.

Delegate this to the **kb-updater** subagent — it carries the full procedure and the boundary rules,
and the work is context-heavy (36 pages of markdown in, a short diff out), which is exactly what a
separate context window is for.

Scope: $ARGUMENTS (empty = all 36 pages; otherwise pass through as `--only <substring>`)

Requirements for the report you give me:
1. Which pages changed, by `content_sha256`.
2. Proposed corpus edits, each quoting the verbatim on-page text and naming the backing raw file.
3. 🔴 Anything touching a negative-knowledge category flagged for my review — do not decide those.
4. Token impact against the 4,096 cache floor.

Do **not** edit `content/knowledge-base.md`. I merge; you propose.
