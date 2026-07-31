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
 * emits, verified by sampling real answers: `**bold**`, `*italic*`, and `` `code` ``.
 *
 * Block structure is *not* handled here. Paragraphs and line breaks already render correctly via
 * `white-space: pre-wrap` on `.message`, so adding block parsing would replace something that
 * works with something that could break.
 *
 * Unmatched delimiters pass through as literal characters — an asterisk in prose stays an
 * asterisk rather than swallowing the rest of the sentence.
 */

// One pass, alternation ordered so `**` is tried before `*`.
const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g

export function renderInline(text) {
  if (!text) return text

  const parts = text.split(INLINE)

  return parts.map((part, i) => {
    if (!part) return null

    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={i}>{part.slice(1, -1)}</em>
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={i}>{part.slice(1, -1)}</code>
    }
    return part
  })
}
