import { useEffect, useRef, useState } from 'react'

import Turn from './Turn.jsx'
import { useChat } from './useChat.js'
import { useScrollToEnd } from './useScrollToEnd.js'

const CLASSES = { turn: 'wg-turn', turnUser: 'wg-turn--user', speaker: 'wg-who' }

/**
 * The support bot as a floating launcher that opens into a chat panel.
 *
 * ⚠️ **No behaviour of its own.** It calls the same `useChat()` as the full page and renders with
 * the same `renderInline()`, so streaming, error frames, multi-turn history, link allowlisting and
 * the server-side refusal marker all behave identically. A second implementation would be a second
 * thing to keep correct — the reason `useChat` was extracted rather than copied.
 *
 * The accessibility work here is the part that is easy to skip and obvious when missing:
 *
 * - Focus moves into the panel on open and returns to the launcher on close. Without the return,
 *   a keyboard user is dropped at the top of the document every time they close the chat.
 * - Escape closes, which is what a dialog is expected to do.
 * - `aria-expanded` on the launcher, `role="dialog"` + `aria-modal="false"` on the panel. Not
 *   modal: the page behind stays usable, which is the point of a widget rather than an overlay.
 * - `aria-live="polite"` on the transcript, so arriving text is announced without interrupting.
 *
 * Sizing rules that only fail on a real phone: the panel is `svh`-based, never `vh` (the iOS
 * keyboard shrinks the viewport and `vh` does not follow), and the input is `≥16px` (anything
 * smaller triggers iOS auto-zoom on focus). Both live in `widget.css` as tokens.
 */
export default function Widget() {
  const [open, setOpen] = useState(false)
  const { messages, input, setInput, send, streaming } = useChat()

  const launcherRef = useRef(null)
  const panelRef = useRef(null)
  const inputRef = useRef(null)
  const endRef = useScrollToEnd([messages, streaming, open])

  // Focus in on open, back to the launcher on close. `wasOpen` avoids stealing focus on first
  // mount, when the panel has never been open and the user may be reading the page.
  const wasOpen = useRef(false)
  useEffect(() => {
    if (open) inputRef.current?.focus()
    else if (wasOpen.current) launcherRef.current?.focus()
    wasOpen.current = open
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div className="wg">
      {open && (
        <section
          className="wg-panel"
          ref={panelRef}
          role="dialog"
          aria-modal="false"
          aria-label="Cadre AI support chat"
        >
          <header className="wg-head">
            <span className="wg-title">Cadre AI — Support</span>
            <button
              className="wg-close"
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close chat"
            >
              ✕
            </button>
          </header>

          <div className="wg-log" role="log" aria-live="polite" aria-label="Conversation">
            {messages.length === 0 && (
              <p className="wg-empty">
                Ask about Cadre&rsquo;s services, industries, or how to book a call.
              </p>
            )}
            {messages.map((m, i) => (
              <Turn
                key={i}
                message={m}
                isLast={i === messages.length - 1}
                streaming={streaming}
                classes={CLASSES}
              />
            ))}
            <div ref={endRef} />
          </div>

          <form className="wg-composer" onSubmit={send}>
            <input
              className="wg-input"
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about Cadre AI…"
              disabled={streaming}
              aria-label="Your question"
            />
            <button className="wg-send" type="submit" disabled={streaming || !input.trim()}>
              {streaming ? '…' : 'Send'}
            </button>
          </form>
        </section>
      )}

      <button
        className="wg-launcher"
        ref={launcherRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? 'Close the support chat' : 'Open the support chat'}
      >
        {open ? '✕' : 'Ask Cadre AI'}
      </button>
    </div>
  )
}
