/**
 * Behavioural audit of link rendering. Exits non-zero on any failure.
 *
 * ⚠️ It imports the REAL `links.js`. An earlier version of this audit kept its own copy of the
 * regexes — because `markdown.jsx` contains JSX and a plain Node script cannot import it — and the
 * copy silently went stale the moment the real pattern changed, reporting a fixed bug as still
 * broken. Splitting the patterns into `links.js` is what makes this a test rather than a mirror.
 *
 * Every other link test in this repo asserts on source strings ("does the file contain X"). This
 * one asserts on behaviour, which is what CLAUDE.md asks for: properties, not strings.
 *
 * Run: node web/scripts/link-audit.mjs   (pytest runs it too — tests/test_links_behaviour.py)
 */
import { CADRE_URLS } from '../src/cadre-urls.js'
import { looksLikeLink, resolveLink, URL_RE } from '../src/links.js'

const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g
const ORIGIN = new URL(CADRE_URLS[0]).origin

/** Mirrors markdown.jsx's structure, emitting strings instead of React elements. */
function linkify(text) {
  if (!text.includes('://') && !text.includes('/')) return text
  return text
    .split(URL_RE)
    .map((piece) => {
      if (!piece || !looksLikeLink(piece)) return piece ?? ''
      const r = resolveLink(piece)
      return r ? `<a href="${r.href}">${r.label}</a>${r.trailing}` : piece
    })
    .join('')
}

function render(text) {
  return text
    .split(INLINE)
    .map((p) => {
      if (!p) return ''
      if (p.startsWith('**') && p.endsWith('**') && p.length > 4) return `<b>${linkify(p.slice(2, -2))}</b>`
      if (p.startsWith('*') && p.endsWith('*') && p.length > 2) return `<i>${linkify(p.slice(1, -1))}</i>`
      if (p.startsWith('`') && p.endsWith('`') && p.length > 2) return `<code>${p.slice(1, -1)}</code>`
      return linkify(p)
    })
    .join('')
}

const failures = []
const linksTo = (out, href) => out.includes(`<a href="${href}">`)
const hasAnyLink = (out) => out.includes('<a href=')

// 1 & 2 — every allowlisted page must link, written either way.
for (const u of CADRE_URLS) {
  const abs = render(`See ${u} for more.`)
  if (!linksTo(abs, u)) failures.push(`absolute form did not link: ${u} → ${abs}`)

  const path = u.replace(ORIGIN, '')
  if (path) {
    const rel = render(`Its page is ${path}.`)
    if (!linksTo(rel, u)) failures.push(`bare path did not link: ${path} → ${rel}`)
  }
}

// 3 — shapes that must produce a link.
const MUST_LINK = [
  'Go to /contact.', 'Go to /contact, then wait.', 'Have you seen /case-studies?',
  'Read /articles!', 'Try this: /industries:', 'Head to **/contact** now.',
  'Head to */contact* now.', 'Book a call (/contact) today.', '/contact is the place.',
  'The page is /contact', 'See /about and /careers here.',
  'Read /articles/ai-model-selection now.', 'See /industries/real-estate for that.',
  'Visit https://www.cadreai.com/contact.', 'Visit **https://www.cadreai.com/contact**.',
  'Our site is https://www.cadreai.com.', 'Visit https://www.cadreai.com/contact/ today.',
  '- /contact — talk to a strategist',
  'Visit HTTPS://WWW.CADREAI.COM/CONTACT today.',
  'Visit https://WWW.CADREAI.COM/Contact today.',
]
for (const t of MUST_LINK) {
  const out = render(t)
  if (!hasAnyLink(out)) failures.push(`expected a link: ${t} → ${out}`)
  const m = out.match(/<a href="([^"]+)"/)
  if (m && !CADRE_URLS.includes(m[1])) failures.push(`href not from the allowlist: ${m[1]}`)
  if (m && /[.,;:!?]$/.test(m[1])) failures.push(`punctuation leaked into href: ${m[1]}`)
}

// 4 — shapes that must NOT produce a link. The safety half.
const MUST_NOT_LINK = [
  'Log in at /ai-agents for access.',       // invented: the real page is /agents
  'Go to /portal/login now.',               // invented portal
  'See https://evil.example.com/cadre now.',
  'See https://cadreai.com.evil.com/x now.', // lookalike host
  'Available and/or on request.',
  'Open 24/7 for support.',
  'Ask him/her about it.',
  'Due 12/31 this year.',
  'Edit /etc/passwd carefully.',
  'Type `/contact` exactly.',                // code span: quoted, not offered
  'Type `https://www.cadreai.com/contact` exactly.',
]
for (const t of MUST_NOT_LINK) {
  const out = render(t)
  if (hasAnyLink(out)) failures.push(`must NOT link: ${t} → ${out}`)
}

// 5 — no prose is ever lost or altered, whatever the shape.
//
// Compared against the input with its markdown delimiters removed, because `**`, `*` and backticks
// are *consumed* by design — that is what formatting means. The first version of this check
// compared against the raw input and reported five failures that were the renderer working
// correctly. A check that flags correct behaviour is worse than no check, because it trains you to
// ignore the output.
const undelimit = (t) => t.replace(/\*\*|\*|`/g, '')
for (const t of [...MUST_LINK, ...MUST_NOT_LINK]) {
  const stripped = render(t).replace(/<[^>]+>/g, '')
  if (stripped !== undelimit(t)) {
    failures.push(`prose changed: ${JSON.stringify(t)} → ${JSON.stringify(stripped)}`)
  }
}

const checks = CADRE_URLS.length * 2 - 1 + MUST_LINK.length + MUST_NOT_LINK.length
if (failures.length) {
  console.error(`link audit: ${failures.length} FAILED of ~${checks}`)
  for (const f of failures) console.error('  - ' + f)
  process.exit(1)
}
console.log(`link audit: ${checks} checks passed (${CADRE_URLS.length} pages x2 forms, ${MUST_LINK.length} shapes, ${MUST_NOT_LINK.length} negatives)`)
