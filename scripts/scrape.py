#!/usr/bin/env python3
"""Build-time corpus scraper for cadreai.com.

Why a real scraper and not an AI fetch tool: `content/raw/` is the provenance record. An
assistant-style fetch returns small-model-extracted markdown — a paraphrase layer,
non-deterministic between runs, with no completeness guarantee. A designated source of truth that
is actually a reworded summary is a contradiction, and it is exactly how the disputed case-study
attribution in the research notes came about. This is byte-faithful and re-runnable, which is
also what makes `kb-updater` possible.

Not shipped in the runtime image (see Dockerfile). Run it, commit the output, and the deployed app
never touches the network.

    uv run --extra scrape python scripts/scrape.py            # full run
    uv run --extra scrape python scripts/scrape.py --only case-studies
    uv run --extra scrape python scripts/scrape.py --list     # show the plan, fetch nothing
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify

BASE = "https://www.cadreai.com"
# Destination for the byte-faithful record. Written ONLY by this script -- never hand-edited,
# because it is the provenance trail every corpus fact is supposed to trace back to.
OUT = Path(__file__).parent.parent / "content" / "raw"

# Identify honestly. robots.txt (checked 2026-07-29) is `User-agent: * / Disallow:` — everything
# permitted — but a real UA and a delay are the courtesy regardless.
UA = "CadreSupportBotScraper/0.1 (+build-time corpus fetch for a Cadre AI support chatbot)"
# Politeness gap between fetches. Not a rate limit we are subject to -- a courtesy so a build-time
# scrape of 36 pages never looks like a burst to the site being read.
DELAY_S = 1.0
TIMEOUT_S = 30

# Prioritised inventory. The sitemap lists 101 URLs; this is the subset the six support scenarios
# actually need. What is skipped, and why, is recorded in SKIPPED below — an unexplained omission in
# a provenance record is worse than no record.
# The explicit fetch list. Enumerated by hand rather than crawled: a crawler's output changes
# silently when the site adds a page, and the corpus needs a fixed, reviewable set.
PAGES: list[str] = [
    # Core
    "/",
    "/about",
    "/contact",
    "/careers",
    "/case-studies",
    "/articles",
    # Services
    "/strategy",
    "/leadership-facilitation",
    "/ai-engineering",
    "/agents",
    "/ai-transformation-intensive",
    # Industries (scenario 1: "do you work with my industry")
    "/industries",
    "/industries/professional-services",
    "/industries/private-equity",
    "/industries/real-estate",
    "/industries/financial-services",
    "/industries/mortgage-lending",
    "/industries/construction",
    "/industries/retail-e-commerce",
    "/industries/manufacturing-logistics",
    "/industries/hospitality",
    # Departments
    "/departments",
    "/departments/sales",
    "/departments/marketing",
    "/departments/customer-success",
    "/departments/executive-leadership",
    "/departments/finance",
    "/departments/operations",
    "/departments/technology",
    "/departments/legal",
    # Legal (scenario 5b: data security)
    "/legal/privacy-policy",
    "/terms-of-service",
    # Podcast landing pages — METADATA TIER ONLY. Episode pages are deliberately not fetched:
    # the bot may name a guest and link the episode, never characterise what was said.
    "/ai-2030-podcast",
    "/2030-podcast",
    # The two articles that directly ground scenario 5a
    "/articles/ai-model-selection",
    "/articles/cadre-ai-selected-as-an-official-openai-service-partner",
]

# Paths deliberately NOT fetched, each with the reason. Recorded rather than omitted, so the gap
# is a decision someone can review instead of an oversight nobody notices.
SKIPPED = {
    "/authors/*": "9 pages. Author bios; no support scenario asks for them.",
    "/podcasts/*": "22 episode pages. Metadata comes from the two landing pages; fetching "
    "episode bodies would invite summarising what a guest said — forbidden (CLAUDE.md).",
    "/articles/* (26 of 28)": "Only the two scenario-5a articles are fetched. The rest are "
    "listed on /articles; the bot needs titles and links, not bodies.",
    "/events/*, /eventsold": "Empty or stale at scrape time; no rule exists for presenting a "
    "past event as upcoming, so the corpus omits them.",
    "/scroller-test-page": "A test page left on the live site.",
}

# Chrome that carries no information: nav, footer, cookie banners, repeated CTAs.
# Elements removed before conversion -- nav, footer, cookie banners. Chrome that repeats on every
# page adds tokens without adding facts.
STRIP_SELECTORS = [
    "nav", "header", "footer", "script", "style", "noscript", "svg", "form",
    '[class*="nav"]', '[class*="footer"]', '[class*="cookie"]', '[class*="banner"]',
    '[aria-hidden="true"]',
]


# Fetch one page over HTTP.
#   in : url -- absolute URL
#   out: the raw HTML as text
#   raises: on any HTTP or network error -- a partial scrape must fail loudly, because a silently
#           missing page becomes a silently missing fact in the corpus.
def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 — fixed https host
        return r.read().decode("utf-8", errors="replace")


# Convert one page to markdown.
#   in : html -- the raw response body
#   out: (title, markdown_body) with STRIP_SELECTORS removed
def to_markdown(html: str) -> tuple[str, str]:
    """Return (title, markdown). Title comes from <h1>, falling back to <title>."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.h1 and soup.h1.get_text(strip=True):
        title = soup.h1.get_text(strip=True)
    elif soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(strip=True).replace(" | Cadre AI", "").strip()

    for sel in STRIP_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    body = soup.body or soup
    md = markdownify(str(body), heading_style="ATX", strip=["a"] if False else None)

    # Collapse the run of blank lines Webflow's markup produces; keep paragraph breaks.
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"[ \t]+\n", "\n", md)
    return title, md.strip()


# Derive the output filename from a URL path.
#   in : path -- e.g. '/industries/construction'
#   out: 'industries--construction' -- a flat name, so content/raw/ stays one directory that can
#        be diffed and counted at a glance.
def slug_for(path: str) -> str:
    s = path.strip("/").replace("/", "--") or "home"
    return f"{s}.md"


# Fetch, convert and write every page.
#   in : paths -- the list to fetch
#   out: (written, unchanged) counts
# Each file carries url / scraped_at / content_sha256 in frontmatter. The hash is what makes
# drift detectable later -- though it is ORDER-SENSITIVE, so a rotating carousel reports a change
# where the content is identical (~77% of flagged pages on the last refresh).
def scrape(paths: list[str]) -> tuple[int, int]:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = fail = 0

    for i, path in enumerate(paths):
        url = BASE + path
        try:
            html = fetch(url)
            title, md = to_markdown(html)
            if len(md) < 80:
                print(f"  ⚠️  {path} — only {len(md)} chars of body; check the selectors")

            # Hash the CONTENT, not the fetch. This is what kb-updater diffs against to detect a
            # silent edit that changes body copy without touching any published date.
            digest = hashlib.sha256(md.encode("utf-8")).hexdigest()

            frontmatter = (
                "---\n"
                f"url: {url}\n"
                f'title: "{title.replace(chr(34), chr(39))}"\n'
                f"scraped_at: {time.strftime('%Y-%m-%d')}\n"
                f"content_sha256: {digest}\n"
                "---\n\n"
            )
            (OUT / slug_for(path)).write_text(frontmatter + md + "\n", encoding="utf-8")
            print(f"  ✓ {path:52} {len(md):>6} chars  {digest[:10]}")
            ok += 1
        except Exception as e:  # noqa: BLE001 — one bad page must not abort the corpus
            print(f"  ✗ {path:52} {type(e).__name__}: {e}")
            fail += 1

        if i < len(paths) - 1:
            time.sleep(DELAY_S)

    return ok, fail


# CLI entry point.
#   flags: --only <substring> to re-fetch a subset
#   out: exit code, 0 on success. Must stay re-runnable: this script is the first link in the
#        provenance chain, and a scrape nobody can reproduce is not evidence.
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring filter on the path")
    ap.add_argument("--list", action="store_true", help="print the plan and exit")
    args = ap.parse_args()

    paths = [p for p in PAGES if args.only in p] if args.only else PAGES

    if args.list:
        print(f"{len(paths)} pages planned:")
        for p in paths:
            print(f"  {p}")
        print("\nDeliberately skipped:")
        for k, v in SKIPPED.items():
            print(f"  {k}\n      {v}")
        return 0

    print(f"Scraping {len(paths)} pages from {BASE} (delay {DELAY_S}s, UA identifies itself)\n")
    ok, fail = scrape(paths)
    print(f"\n{ok} ok, {fail} failed → {OUT}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
