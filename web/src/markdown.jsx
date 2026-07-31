/**
 * A deliberately tiny inline-markdown renderer for assistant text.
 *
 * ⚠️ **It returns React elements, never HTML.** `dangerouslySetInnerHTML` would be the obvious
 * shortcut and it is an injection vector: the string being rendered is model output, and model
 * output is influenced by whatever the user typed. A tokeniser that emits elements cannot inject
 * markup no matter what arrives, because React escapes text nodes by construction.
 *
 * ⚠️ **No markdown library.** `CLAUDE.md` keeps the frontend at two dependencies and rules out
 * component kits for the same reason. `react-markdown` pulls a remark/unified tree — a large,
 * permanently-owned dependency to render bold text. This handles exactly what the model actually
 * emits, verified by sampling real answers: `**bold**`, `*italic*`, `` `code` ``, and bare URLs.
 *
 * Block structure is *not* handled here. Paragraphs and line breaks already render correctly via
 * `white-space: pre-wrap` on `.message`, so adding block parsing would replace something that
 * works with something that could break.
 *
 * Unmatched delimiters pass through as literal characters — an asterisk in prose stays an
 * asterisk rather than swallowing the rest of the sentence.
 *
 * ## Links
 *
 * ⚠️ **Only URLs in `cadre-urls.js` become links, and the `href` is taken from that constant —
 * never from the reply.** Bare paths (`/contact`) resolve through the same list as absolute URLs,
 * because the model writes both and a path that printed as dead text was the inconsistency users
 * noticed first. A URL the model was talked into inventing renders as plain text, which
 * is exactly what it did before links existed. See the header of `cadre-urls.js` for why an
 * allowlist rather than a general linkifier: making every URL clickable would turn a *content*
 * boundary into a *clickable* one.
 */

import { looksLikeLink, resolveLink, URL_RE } from './links.js'

// One pass, alternation ordered so `**` is tried before `*`.
const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g

// The matching patterns and the resolve step live in `links.js`, so the audit script can import
// the real ones. A harness that copies a regex tests the copy, and the copy goes stale silently.

/**
 * Split `text` on URLs, linking only those the corpus proves exist.
 *
 * Runs inside the bold/italic branches too, so `**https://www.cadreai.com/contact**` is a link
 * inside a `<strong>` rather than bold plain text — the model does emit that shape, and the eval
 * has caught a markdown-bolded `/contact` before.
 */
function linkify(text, keyPrefix) {
  if (!text.includes('://') && !text.includes('/')) return text

  return text.split(URL_RE).map((piece, i) => {
    if (!piece || !looksLikeLink(piece)) return piece || null

    // `href` is the canonical string from the allowlist; the matched text is only ever a key and
    // never reaches the DOM as an href.
    const resolved = resolveLink(piece)
    if (!resolved) return piece

    return (
      <span key={`${keyPrefix}-${i}`}>
        {/* `noopener noreferrer` is not optional with `_blank`: without it the opened page gets
            a live `window.opener` handle back to this one. */}
        <a href={resolved.href} target="_blank" rel="noopener noreferrer">
          {resolved.label}
        </a>
        {resolved.trailing}
      </span>
    )
  })
}

export function renderInline(text) {
  if (!text) return text

  const parts = text.split(INLINE)

  return parts.map((part, i) => {
    if (!part) return null

    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i}>{linkify(part.slice(2, -2), i)}</strong>
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={i}>{linkify(part.slice(1, -1), i)}</em>
    }
    // Code spans are left alone on purpose: a URL shown as code is being quoted, not offered.
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={i}>{part.slice(1, -1)}</code>
    }
    return linkify(part, i)
  })
}
