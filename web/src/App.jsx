import { useEffect, useRef } from 'react'

import { renderInline } from './markdown.jsx'
import { useChat } from './useChat.js'

/**
 * The full-page chat view.
 *
 * The conversation engine — the POST, the SSE reader, frame buffering, delta accumulation, error
 * frames, first-token timing — lives in `useChat()`. It was inline here until the floating widget
 * needed the same behaviour; copying it would have created a second SSE parser, and the two would
 * have drifted. This component is now layout only.
 *
 * No inline styles: every rule lives in app.css and every value in tokens.css. Guarded by
 * tests/test_ui.py so it stays that way.
 */
export default function App() {
  const { messages, input, setInput, send, streaming, firstTokenMs } = useChat()
  const endRef = useRef(null)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    endRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' })
  }, [messages, streaming])

  return (
    <div className="chat">
      <header className="header">
        <h1 className="title">Cadre AI — Support</h1>
        <p className="subtitle">
          Ask about Cadre&rsquo;s services, industries, the AI Maturity Index, or how to book a call.
          For anything that isn&rsquo;t public — pricing, portal access, engagement specifics — you
          will be pointed to the team rather than given a guess.
        </p>
      </header>

      <div className="transcript" role="log" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && <p className="empty">No messages yet.</p>}
        {messages.map((m, i) => (
          <p className={m.role === 'user' ? 'turn turn--user' : 'turn'} key={i}>
            <span className="speaker">{m.role === 'user' ? 'You' : 'Cadre AI'}</span>
            <span className={m.isError ? 'message message--error' : 'message'}>
              {/* The user's own text is rendered literally — they typed it, and interpreting
                  their asterisks would be surprising. Only assistant prose is formatted. */}
              {m.role === 'assistant' && !m.isError ? renderInline(m.content) : m.content}
              {streaming && i === messages.length - 1 && m.role === 'assistant' && (
                <span className="caret">▍</span>
              )}
            </span>
          </p>
        ))}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={send}>
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about Cadre AI…"
          disabled={streaming}
          aria-label="Your question"
        />
        <button className="send" type="submit" disabled={streaming || !input.trim()}>
          {streaming ? '…' : 'Send'}
        </button>
      </form>

      {firstTokenMs !== null && (
        <p className="diagnostic">time to first token: {firstTokenMs}ms</p>
      )}

      <p className="footer">
        Answers come only from Cadre&rsquo;s public site. Anything else routes to{' '}
        <a href="https://www.cadreai.com/contact">cadreai.com/contact</a>.
      </p>
    </div>
  )
}
