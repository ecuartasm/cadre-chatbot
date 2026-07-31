---
name: edit-system-prompt
description: Use when changing app/llm/prompt.py — the persona, grounding rule, boundary rules, refusal marker, conversion behavior, or format section. A prompt edit touches five files and has a silent failure mode below the 4,096-token cache floor. Also use when asked to make the bot stricter, looser, or differently worded about what it will answer.
---

# Editing the system prompt

A prompt edit here is never a one-file change. It touches five, and the failure it can cause is
**silent**: below `claude-haiku-4-5`'s 4,096-token minimum cacheable prefix, caching stops with no
error, no warning, and no symptom other than every turn costing ~6× more forever
($0.00120 cached → $0.00627 uncached).

Done by hand eleven times now. The bookkeeping was botched twice before this skill existed — a
history entry inserted out of order carrying a stale value, and a docstring claiming 4,954 while the
constant said 5,050. Neither broke the bot; both are the drift that makes the next reader stop
trusting the file. Since the skill, zero.

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
pytest && ruff check .                                    # structure only
python eval/golden.py --url http://localhost:8000         # lite: 14 cases, ~$0.03, ~2 min
```

**Run the lite suite after EVERY prompt edit, before deploying.** It is two minutes and three cents,
and every prompt defect in this build passed a green `pytest` first. The unit tests check that the
prompt is *assembled* correctly; only the eval checks that the model still *behaves*.

Then **probe the specific behaviour you changed** by hand. The eval tells you nothing broke; it
cannot tell you whether the thing you were trying to change actually changed. Adding "friendly" to
the persona passed everything and moved nothing — the tone was identical, which only a probe showed.

### When to run `--suite full` as well

**Any edit to `_BOUNDARY` or `_MARKER`, and any change to voice or tone.** 71 cases, ~$0.15, ~6 min.

This is not caution for its own sake — the full suite exists because every prompt defect here came
through an *oblique* route the lite set does not cover:

| Found by | Defect |
|---|---|
| lite (Phase 6) | A case-study saving quoted beside a pricing question |
| **full** | The bot inventing "what costs $50k for one company might cost $500k for another" |
| **full** | Reciting its entire refusal vocabulary when asked for "internal reason codes" |
| **full** | A user-supplied `[[refusal:…]]` suppressing the classification |

Tone edits especially: a friendlier voice made the model treat a repeat decline as conversational and
stop tagging it — 2 failures in 6 runs, where the same boundary text with the old persona passed 6/6.
The boundary held; the *measurement* did not. `--tag injection` and `--tag multiturn` slice it when
you only need one dimension.

**Reading a `full` failure:** a *boundary* failure (price, invented URL, client name, prompt leak) is
a defect and blocks the change. A *tagging* failure — refused correctly in prose but `status="ok"` —
is the known under-reporting, measured at ~7% and concentrated in soft refusals. Do not chase it as
a bug; do notice if it rises sharply, because that is what a tone change looks like.

**Non-determinism is a signal, not noise.** If a case fails once and passes on re-run, the behaviour
is on a knife-edge rather than fine. Run it five times and count — that is how the "$50k/$500k" leak
was pinned at 1-in-5 rather than dismissed.

Finally, deploy and re-run lite against the deployed URL — see the `verify-in-production` skill for
the deploy traps. A prompt change is not done until it passes there, because the eval has already
caught a defect that passed locally minutes earlier.

## What not to do

- **Don't trim prose to "tidy up".** Trimming *costs* money here; the floor inverts the usual instinct.
- **Don't skip the version bump** because the change felt small. The version is what makes the logs
  comparable — and every tone edit so far has had a side effect worth being able to attribute.
- **Don't add a rule without deciding where it applies.** See §1.
- **Don't declare a tone change successful because it reads better to you.** Measure it. Count
  pronouns, count refusals by reason, run the case five times. "friendly" felt like a change and
  moved nothing; the voice rewrite that did work also broke the tagging, and only counting showed it.
- **Don't skip the eval because the edit was one word.** v1.6 was one clause and it dropped the
  pushback tag 2-in-6. The size of a prompt edit does not predict the size of its effect.
