import { knownCadreUrl } from './cadre-urls.js'

/**
 * Link *matching* — the patterns and the resolve step, with no rendering.
 *
 * Split out of `markdown.jsx` so the audit can import the real thing. `markdown.jsx` contains JSX
 * and cannot be imported by a plain Node script, so the audit previously kept its own copy of these
 * regexes — which meant it was testing a duplicate, and the duplicate silently went stale the first
 * time the real one changed. A test that copies the code under test is not a test of that code.
 */

// Absolute URLs, then bare site paths — in that order, so `https://www.cadreai.com/contact` is
// consumed whole rather than having its path half re-matched.
//
// Brackets and quotes are excluded so a parenthesised link does not swallow its own closing paren;
// trailing sentence punctuation is trimmed by `TRAILING` below.
//
// The path branch is deliberately loose: `and/or`, `24/7`, `he/she` and `/etc/passwd` all match it.
// That is harmless, because matching is not what creates a link — **the allowlist lookup is** — and
// none of them is a Cadre page, so each falls through to plain text unchanged. The tempting fix is
// a stricter pattern, which would start rejecting real pages as the corpus grows.
//
// Case-insensitive because `canonicalise()` already lowercases before comparing. Without the flag
// the matcher and the lookup disagreed: `HTTPS://WWW.CADREAI.COM/CONTACT` failed to match at all
// while `https://WWW.CADREAI.COM/Contact` linked fine. Found by auditing all 36 pages rather than
// by reading — it is not a shape the model has ever actually produced.
export const URL_RE = /(https?:\/\/[^\s<>()[\]"']+|\/[a-z0-9][a-z0-9-]*(?:\/[a-z0-9-]+)*)/gi

// A URL at the end of a sentence — "…see /contact." — must not carry the full stop into the href.
// Without this the lookup misses and the link silently does not render, which is the single most
// common way a naive linkifier fails.
const TRAILING = /[.,;:!?]+$/

/** True if `piece` is worth attempting to resolve. */
export function looksLikeLink(piece) {
  const lower = (piece ?? '').toLowerCase()
  return lower.startsWith('http') || lower.startsWith('/')
}

/**
 * Resolve one matched piece.
 *
 * Returns `{ href, label, trailing }` when the target is a page the corpus proves exists, or
 * `null` when it is not — in which case the caller renders the text unchanged.
 *
 * ⚠️ `href` is the canonical string from the allowlist; `label` is what the model wrote. The text
 * being resolved is never the href, so an href can only ever be one of the allowlisted constants.
 */
export function resolveLink(piece) {
  const trailing = piece.match(TRAILING)?.[0] ?? ''
  const label = trailing ? piece.slice(0, -trailing.length) : piece
  const href = knownCadreUrl(label)
  return href ? { href, label, trailing } : null
}
