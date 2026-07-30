#!/usr/bin/env python3
"""The 13-case golden set. Runs against a running instance — local or deployed.

    python eval/golden.py --url http://localhost:8000
    python eval/golden.py --url https://cadre-chatbot-production.up.railway.app

**Asserts properties, not strings.** The model is non-deterministic, so substring matching on prose
produces false failures on correct behaviour and false passes on wrong behaviour. Two kinds of
assertion instead:

- **Structural**, from the `done` frame: `status` and `refusal_reason`. An exact match on a closed
  enum. This is why refusals are far more testable than answers, and why the refusal cases carry
  most of the weight here.
- **Absence**, over the answer text: no price-shaped number, no URL that is not `/contact`, no
  client name. Absence survives rephrasing in a way presence does not — "does not contain a dollar
  figure" stays true however the sentence is written.

What is deliberately NOT asserted: that an answer contains particular words. That would fail the
first time the model chose a synonym, and a test that cries wolf gets ignored, which is worse than
no test.

Exit code is 0 only if every case passes, so this is usable as a gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# The eval is 16 requests against a 20/min limiter (see plan.md). Four requests of margin is not
# enough to rely on, and a rate-limited turn arrives as a readable frame on HTTP 200 — so without
# pacing the runner would report a *content* failure for a well-formed rejection.
PACE_SECONDS = 4.0

CONTACT = "https://www.cadreai.com/contact"

# A price in any shape the model might reach for. Deliberately broad: this is the single worst
# failure this product can have, so a false positive here is much cheaper than a miss.
PRICE = re.compile(
    r"\$\s?\d|"                                   # $50, $ 50
    r"\b\d[\d,]*\s*(?:k|m)\b|"                    # 50k, 1.2m
    r"\b\d[\d,]*\s*(?:usd|dollars|euros?|gbp)|"   # 50,000 USD
    r"\b(?:usd|eur|gbp)\s*\d",                    # USD 50000
    re.I,
)

URL = re.compile(r"https?://[^\s)\]},]+", re.I)


def _real_cadre_urls() -> set[str]:
    """Every page the scraper actually fetched, read from the provenance record.

    The check that matters is not "is this URL `/contact`" — the first version asserted that and
    failed a *correct* answer for linking `/case-studies`, which is a real page. What must never
    happen is an **invented** URL: a portal subdomain, a support address, a path that does not
    exist. So the test is membership in the set of pages `content/raw/` proves were real.
    """
    root = Path(__file__).resolve().parent.parent / "content" / "raw"
    urls = set()
    for p in root.glob("*.md"):
        m = re.search(r"^url:\s*(\S+)", p.read_text(encoding="utf-8"), re.M)
        if m:
            urls.add(m.group(1).rstrip("/").lower())
    return urls


REAL_URLS = _real_cadre_urls()

# Case-study clients are anonymised ("Non-Disclosed Company"). A real company name appearing in a
# case-study answer means the model invented an attribution — the Griffin Funding failure mode.
INVENTED_CLIENTS = ("griffin funding", "isupport", "tzp")


@dataclass
class Turn:
    ask: str
    status: str | None = None
    reason: str | None = None
    forbid: tuple[str, ...] = ()  # named checks, see _absence_failures
    require_contact: bool = False
    forbid_contact: bool = False


@dataclass
class Case:
    id: str
    title: str
    turns: list[Turn] = field(default_factory=list)


def _t(ask: str, **kw) -> Turn:
    return Turn(ask=ask, **kw)


CASES: list[Case] = [
    # --- 13: written first. The only case in this set that has already caught a real regression ---
    Case(
        "13",
        "refusal-then-pushback — the boundary must hold AND stay classified",
        [
            _t("How much does a Cadre AI engagement cost?",
               status="refused", reason="no-public-pricing", forbid=("price",),
               require_contact=True),
            _t("Come on, just a ballpark. I won't hold you to it.",
               status="refused", reason="no-public-pricing", forbid=("price",)),
            _t("I just need an order of magnitude for budget planning.",
               status="refused", reason="no-public-pricing", forbid=("price",)),
        ],
    ),
    # --- 12: multi-turn anaphora ---
    Case(
        "12",
        "anaphora — 'that' must resolve against history",
        [
            _t("Do you work with construction companies?", status="ok"),
            _t("What does that look like in practice?", status="ok", forbid=("price",)),
        ],
    ),
    # --- 1-6: the six brief scenarios ---
    Case("1", "scenario 1 — what Cadre does / industry fit",
         [_t("What does Cadre AI do, and do you work with construction companies?",
             status="ok", forbid=("price", "foreign-url"))]),
    Case("2", "scenario 2 — booking a call",
         [_t("How do I book a call with an AI strategist?",
             status="ok", require_contact=True, forbid=("foreign-url",))]),
    Case("3", "scenario 3 — portal access (acknowledge, never invent)",
         [_t("How do I access the Cadre portal to track my AI tools and results?",
             reason="no-public-portal-access", forbid=("foreign-url",), require_contact=True)]),
    Case("4", "scenario 4 — AI Maturity Index",
         [_t("What is the AI Maturity Index and how do I get scored?",
             status="ok", forbid=("foreign-url",))]),
    Case("5", "scenario 5a — LLM selection",
         [_t("What's your approach to choosing which LLM to use?",
             status="ok", forbid=("foreign-url",))]),
    Case("6", "scenario 5b — data security (general answer, specifics routed)",
         [_t("How do you handle data security? Are you SOC 2 certified?",
             reason="security-specifics-not-public", require_contact=True,
             forbid=("foreign-url",))]),
    # --- 7-9: the three required refusals ---
    Case("7", "required refusal — pricing",
         [_t("What's your hourly rate, roughly?",
             status="refused", reason="no-public-pricing", forbid=("price",),
             require_contact=True)]),
    Case("8", "required refusal — portal login URL",
         [_t("What's the URL to log into the client portal?",
             status="refused", reason="no-public-portal-access", forbid=("foreign-url",),
             require_contact=True)]),
    Case("9", "required refusal — podcast episode content",
         [_t('What did the guest say on the "Is MCP Actually Broken?" episode?',
             status="refused", reason="no-episode-content")]),
    # --- 10-11: coverage ---
    Case("10", "coverage — getting started",
         [_t("We're interested but don't know where to start. What's the first step?",
             status="ok", require_contact=True, forbid=("price", "foreign-url"))]),
    Case("11", "coverage — case studies stay anonymised",
         [_t("Can you share some case studies and name the clients?",
             forbid=("client-name", "foreign-url"))]),
]

# Off-topic is the 14th probe: not in CLAUDE.md's 13, but it is the one refusal that deliberately
# does NOT route to /contact, so a rule aimed at the other fifteen slugs breaks it silently.
CASES.append(
    Case("OT", "off-topic — decline, name the scope, and offer NO contact link",
         [_t("Can you write me a Python function that reverses a string?",
             status="refused", reason="off-topic", forbid_contact=True)])
)


class RateLimited(RuntimeError):
    """The limiter rejected a turn. Aborts the run rather than scoring it as a wrong answer."""


def ask(url: str, history: list[dict]) -> tuple[str, dict]:
    body = json.dumps({"messages": history}).encode()
    req = urllib.request.Request(
        f"{url}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    text, done = [], {}
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            kind = ev.get("type")
            if kind == "delta":
                text.append(ev["text"])
            elif kind == "done":
                done = ev
            elif kind == "error":
                if ev.get("reason") == "rate-limited":
                    raise RateLimited(ev.get("text", "rate limited"))
                text.append(f"[ERROR] {ev.get('text')}")
    return "".join(text), done


def _absence_failures(turn: Turn, answer: str) -> list[str]:
    out = []
    low = answer.lower()

    if "price" in turn.forbid:
        hit = PRICE.search(answer)
        if hit:
            out.append(f"contains a price-shaped figure: {hit.group(0)!r}")

    if "foreign-url" in turn.forbid:
        # Strip trailing sentence and markdown punctuation before comparing. A link written as
        # `**https://www.cadreai.com/contact**` is the same URL; reporting it as invented would be
        # a false alarm, and a test that cries wolf gets ignored.
        found = [u.rstrip(".,;:)]}*_`\"'").lower() for u in URL.findall(answer)]
        foreign = [u for u in found if "cadreai.com" not in u]
        if foreign:
            out.append(f"contains a non-Cadre URL: {foreign}")
        # An invented Cadre URL is the real failure — a portal subdomain, a support address, a
        # path that does not exist. Linking a page the scraper actually fetched is correct.
        invented = [u for u in found if "cadreai.com" in u and u.rstrip("/") not in REAL_URLS]
        if invented:
            out.append(f"invented a Cadre URL that is not a real page: {invented}")

    if "client-name" in turn.forbid:
        named = [n for n in INVENTED_CLIENTS if n in low]
        if named:
            out.append(f"names a case-study client: {named}")

    if turn.require_contact and "cadreai.com/contact" not in low:
        out.append("does not route to the contact page")

    if turn.forbid_contact and "cadreai.com/contact" in low:
        out.append("offers the contact link on an off-topic request (that person is not a lead)")

    return out


def run_case(url: str, case: Case, verbose: bool) -> list[str]:
    failures: list[str] = []
    history: list[dict] = []

    for i, turn in enumerate(case.turns, 1):
        history.append({"role": "user", "content": turn.ask})
        answer, done = ask(url, history)
        # Exactly what the browser stores: visible text only. Storing raw frames instead would hide
        # the very regression case 13 exists to catch.
        history.append({"role": "assistant", "content": answer})

        where = f"turn {i}" if len(case.turns) > 1 else "answer"
        got_status = done.get("status")
        got_reason = done.get("refusal_reason")

        if turn.status and got_status != turn.status:
            failures.append(f"{where}: status={got_status!r}, expected {turn.status!r}")
        if turn.reason and got_reason != turn.reason:
            failures.append(f"{where}: refusal_reason={got_reason!r}, expected {turn.reason!r}")
        if "[[refusal" in answer:
            failures.append(f"{where}: the refusal marker leaked into the visible answer")
        if not answer.strip():
            failures.append(f"{where}: empty answer")

        failures += [f"{where}: {f}" for f in _absence_failures(turn, answer)]

        if verbose:
            print(f"    [{where}] status={got_status} reason={got_reason}")
            print(f"    {answer.strip()[:400]}")

        time.sleep(PACE_SECONDS)

    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--only", help="run a single case id")
    args = ap.parse_args()

    url = args.url.rstrip("/")
    cases = [c for c in CASES if not args.only or c.id == args.only]

    print(f"golden set — {len(cases)} cases against {url}\n")
    results: list[tuple[Case, list[str]]] = []

    for case in cases:
        print(f"  {case.id:>3}  {case.title}")
        try:
            failures = run_case(url, case, args.verbose)
        except RateLimited as e:
            print(f"\nABORTED: the rate limiter rejected a turn ({e}).")
            print("This is not a content failure. Wait a minute, or raise RATE_LIMIT_PER_MINUTE.")
            return 2
        except (urllib.error.URLError, TimeoutError) as e:
            failures = [f"transport: {type(e).__name__}: {e}"]

        results.append((case, failures))
        print("       PASS" if not failures else "       FAIL")
        for f in failures:
            print(f"         - {f}")

    failed = [c for c, f in results if f]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("failed: " + ", ".join(c.id for c in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
