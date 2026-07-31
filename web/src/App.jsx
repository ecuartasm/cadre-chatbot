import { useEffect, useRef, useState } from 'react'

/**
 * Reads the SSE body with fetch + ReadableStream rather than EventSource, because EventSource
 * cannot issue a POST and the conversation has to go in the request body.
 *
 * ⚠️ `send` is behaviour under test, not layout. It accumulates only the visible delta text into
 * the assistant turn and posts the whole array back, and multi-turn correctness depends on both
 * halves — the refusal marker is stripped server-side, so storing raw frames instead would put it
 * into history and undo Phase 4. Style this component freely; leave that loop alone.
 *
 * No inline styles: every rule lives in app.css and every value in tokens.css. Guarded by
 * tests/test_ui.py so it stays that way.
 */
export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [firstTokenMs, setFirstTokenMs] = useState(null)
  const endRef = useRef(null)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    endRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' })
  }, [messages, streaming])

  async function send(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || streaming) return

    const next = [...messages, { role: 'user', content: text }]
    setMessages(next)
    setInput('')
    setStreaming(true)
    setFirstTokenMs(null)

    // Placeholder assistant turn we append deltas into as they arrive.
    setMessages((m) => [...m, { role: 'assistant', content: '' }])

    const started = performance.now()
    let sawFirstToken = false

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: next }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line. A frame can arrive split across
        // reads, so only consume complete ones and keep the remainder buffered.
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          const line = frame.split('\n').find((l) => l.startsWith('data: '))
          if (!line) continue
          const evt = JSON.parse(line.slice(6))

          if (evt.type === 'delta') {
            if (!sawFirstToken) {
              sawFirstToken = true
              // If this lands close to the total response time, the proxy buffered
              // the stream — the failure mode this phase exists to catch.
              setFirstTokenMs(Math.round(performance.now() - started))
            }
            setMessages((m) => {
              const copy = [...m]
              copy[copy.length - 1] = {
                role: 'assistant',
                content: copy[copy.length - 1].content + evt.text,
              }
              return copy
            })
          } else if (evt.type === 'error') {
            setMessages((m) => {
              const copy = [...m]
              copy[copy.length - 1] = { role: 'assistant', content: evt.text, isError: true }
              return copy
            })
          }
        }
      }
    } catch (err) {
      setMessages((m) => {
        const copy = [...m]
        copy[copy.length - 1] = {
          role: 'assistant',
          content: `Couldn't reach the server (${err.message}). Please try again.`,
          isError: true,
        }
        return copy
      })
    } finally {
      setStreaming(false)
    }
  }

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
          <p className="turn" key={i}>
            <span className="speaker">{m.role === 'user' ? 'You' : 'Cadre AI'}</span>
            <span className={m.isError ? 'message message--error' : 'message'}>
              {m.content}
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
