/**
 * Every Cadre page the scraper actually fetched — the ONLY URLs the chat will turn into links.
 *
 * ⚠️ **GENERATED from `content/raw/*.md` frontmatter. Do not hand-edit.**
 * `tests/test_ui.py::test_the_link_allowlist_matches_the_scraped_corpus` fails if this drifts,
 * and prints the regenerate command.
 *
 * ## Why an allowlist rather than "linkify anything that looks like a URL"
 *
 * The text being rendered is **model output**, and model output is shaped by whatever the user
 * typed. Linkifying freely would convert a *content* boundary into a *clickable* one: today a
 * URL an injection attempt talked the model into emitting is inert text nobody can click.
 *
 * ⚠️ **The `href` is never model output.** A match here is used to look up the canonical string
 * from this array, and *that* is what reaches the DOM. So an `href` can only ever be one of the
 * 36 constants below — not a substring of a reply, however it was influenced. That is a
 * stronger guarantee than sanitising, because there is nothing left to sanitise.
 *
 * It also covers the KB's own rule: an invented portal URL renders as plain text rather than as a
 * clickable link that looks official. Unknown URL → plain text, which is the pre-existing
 * behaviour, so the failure mode is a no-op.
 */

export const CADRE_URLS = [
  'https://www.cadreai.com',
  'https://www.cadreai.com/2030-podcast',
  'https://www.cadreai.com/about',
  'https://www.cadreai.com/agents',
  'https://www.cadreai.com/ai-2030-podcast',
  'https://www.cadreai.com/ai-engineering',
  'https://www.cadreai.com/ai-transformation-intensive',
  'https://www.cadreai.com/articles',
  'https://www.cadreai.com/articles/ai-model-selection',
  'https://www.cadreai.com/articles/cadre-ai-selected-as-an-official-openai-service-partner',
  'https://www.cadreai.com/careers',
  'https://www.cadreai.com/case-studies',
  'https://www.cadreai.com/contact',
  'https://www.cadreai.com/departments',
  'https://www.cadreai.com/departments/customer-success',
  'https://www.cadreai.com/departments/executive-leadership',
  'https://www.cadreai.com/departments/finance',
  'https://www.cadreai.com/departments/legal',
  'https://www.cadreai.com/departments/marketing',
  'https://www.cadreai.com/departments/operations',
  'https://www.cadreai.com/departments/sales',
  'https://www.cadreai.com/departments/technology',
  'https://www.cadreai.com/industries',
  'https://www.cadreai.com/industries/construction',
  'https://www.cadreai.com/industries/financial-services',
  'https://www.cadreai.com/industries/hospitality',
  'https://www.cadreai.com/industries/manufacturing-logistics',
  'https://www.cadreai.com/industries/mortgage-lending',
  'https://www.cadreai.com/industries/private-equity',
  'https://www.cadreai.com/industries/professional-services',
  'https://www.cadreai.com/industries/real-estate',
  'https://www.cadreai.com/industries/retail-e-commerce',
  'https://www.cadreai.com/leadership-facilitation',
  'https://www.cadreai.com/legal/privacy-policy',
  'https://www.cadreai.com/strategy',
  'https://www.cadreai.com/terms-of-service',
]

/** Canonical form for comparison: lowercase, no trailing slash. */
export function canonicalise(url) {
  return url.toLowerCase().replace(/\/+$/, '')
}

const BY_CANONICAL = new Map(CADRE_URLS.map((u) => [canonicalise(u), u]))

/** The canonical URL for `candidate`, or null if it is not a page we proved exists. */
export function knownCadreUrl(candidate) {
  return BY_CANONICAL.get(canonicalise(candidate)) ?? null
}
