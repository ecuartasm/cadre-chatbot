import { useEffect, useRef } from 'react'

/**
 * Keep a transcript scrolled to its newest turn.
 *
 * Three components wanted this and each carried its own copy — small enough to look harmless, and
 * exactly the shape that drifts: the `prefers-reduced-motion` check is easy to forget in the third
 * copy, and nothing would fail if it were.
 *
 * Respecting `prefers-reduced-motion` is not decoration. Smooth-scrolling a streaming transcript is
 * continuous motion for as long as the answer takes, which is precisely what the setting exists to
 * suppress.
 *
 * Returns a ref to attach to a sentinel `<div>` at the end of the list.
 */
export function useScrollToEnd(deps) {
  const endRef = useRef(null)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    endRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return endRef
}
