---
name: edit-system-prompt
description: Use when changing app/llm/prompt.py — the persona, grounding rule, boundary rules, refusal marker, conversion behavior, or format section. A prompt edit touches five files and has a silent failure mode below the 4,096-token cache floor. Also use when asked to make the bot stricter, looser, or differently worded about what it will answer.
---

# Editing the system prompt

A prompt edit here is never a one-file change. It touches five, and the failure it can cause is
**silent**: below `claude-haiku-4-5`'s 4,096-token minimum cacheable prefix, caching stops with no
error, no warning, and no symptom other than every turn costing ~6× more forever
($0.00120 cached → $0.00627 uncached).

This was done by hand six times during the build and the bookkeeping was botched twice — a history
entry inserted out of order carrying a stale value, and a docstring left claiming 4,954 while the
constant said 5,050. Neither broke the bot; both are the kind of drift that makes the next reader
stop trusting the file.

## 1. Make the edit

`app/llm/prompt.py`. Sections in assembly order: `_PERSONA` · `_FACTS` (the corpus) · `_GROUNDING` ·
`_BOUNDARY` · `_MARKER` · `_CONVERSION` · `_FORMAT`.

Order is deliberate — `_FACTS` sits second so the corpus dominates the prefix, and the rules that
reference it come after, where "the table in your knowledge" resolves to something already read.

⚠️ **Byte-stability.** No timestamp, `request_id`, session id, or per-user string may appear anywhere
in the system block. Caching is a prefix match; one dynamic byte disables it for every turn. Anything
per-request goes in `messages`.

### Two lessons about *where* a rule goes

Both cost a live-probe cycle to discover, and both are about placement rather than wording:

- **A rule the model must apply has to be stated where it applies.** The off-topic rule lived as a
  sub-clause about the contact link; the model obeyed the "no link" half and answered the coding
  question anyway. Promoting it to a hard rule in `_BOUNDARY`, phrased against the actual failure
  ("do NOT answer it, even though you easily could"), fixed it.
- **State the consequence the model can't see.** The marker is stripped before display, so on a
  pushback turn the model reads its own earlier refusals as untagged and concludes tagging is
  optional. Telling it that explicitly — "your earlier replies will look untagged; that does not mean
  the tag became optional" — fixed a case where the boundary held in prose while the *measurement* of
  it silently failed.

## 2. Measure — do not estimate

```bash
uv run python .claude/skills/edit-system-prompt/measure-prefix.py
```

It reports the live `count_tokens` value, the drift against what's recorded, the margin over the
floor, and exactly which bookkeeping to update. Exit 1 means something needs your attention.

**If it says you're below the floor: do not deploy.** Add real content back — content a scenario
actually needs — rather than padding. That is how the corpus got to 4,415 in Phase 1: nine
per-industry value propositions scenario 1 genuinely lacked, not filler.

## 3. Update all four places the number lives

The script names these, but they are easy to half-do:

1. `MEASURED_SYSTEM_TOKENS` — the constant. A test fails past 150 drift.
2. The **history comment** above it — append a line with the new value *and why it changed*. Append,
   don't insert; the list is chronological and reads as a record of what the bot learned.
3. The `Measured at N tokens ... M tokens of margin` figure in `build_system_blocks()`'s docstring.
4. `SYSTEM_PROMPT_VERSION` — bump it. Log lines from two different prompts are otherwise
   indistinguishable, which makes any before/after comparison in `interactions.jsonl` impossible.

## 4. Verify behaviour, not just numbers

```bash
pytest && ruff check .
```

Then **probe the actual behaviour you changed** against a local server before deploying. The tests
check structure; they cannot tell you whether the model now does what you meant. Both prompt bugs
above passed a green suite.

Finally, deploy and run the golden set — see the `verify-in-production` skill, which covers the deploy
traps. A prompt change is not done until 14/14 passes against the deployed URL, because the eval has
already caught one prompt defect that passed locally minutes earlier (a case-study saving cited beside
a pricing question — correct in isolation, an anchor next to a cost question).

## What not to do

- **Don't trim prose to "tidy up".** Trimming *costs* money here; the floor inverts the usual instinct.
- **Don't skip the version bump** because the change felt small. The version is what makes the logs
  comparable.
- **Don't add a rule without deciding where it applies.** See §1.
