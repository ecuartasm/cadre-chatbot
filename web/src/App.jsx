import Turn from './Turn.jsx'
import { useChat } from './useChat.js'
import { useScrollToEnd } from './useScrollToEnd.js'

// Class names differ between the two surfaces; the turn's behaviour does not. See Turn.jsx.
const CLASSES = { turn: 'turn', turnUser: 'turn--user', speaker: 'speaker' }

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
  const endRef = useScrollToEnd([messages, streaming])

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
