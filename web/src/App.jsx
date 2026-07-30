import { useEffect, useRef, useState } from 'react'

/**
 * Phase 0c: deliberately unstyled. The point of this phase is to prove tokens stream
 * end-to-end through the proxy — brand tokens and real CSS land in Phase 5.
 *
 * Reads the SSE body with fetch + ReadableStream rather than EventSource, because
 * EventSource cannot issue a POST and the conversation has to go in the request body.
 */
export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [firstTokenMs, setFirstTokenMs] = useState(null)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
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
    <main style={{ maxWidth: 680, margin: '0 auto', padding: 16, fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 18 }}>Cadre AI — Support</h1>
      <p style={{ fontSize: 13, color: '#666' }}>
        Phase 0c vertical slice: three hardcoded facts, unstyled. Try “what does Cadre do?”,
        “how do I book a call?”, or “how much does it cost?” — the last one should refuse.
      </p>

      <div style={{ border: '1px solid #ddd', padding: 12, minHeight: 260, marginBottom: 12 }}>
        {messages.length === 0 && <p style={{ color: '#999' }}>No messages yet.</p>}
        {messages.map((m, i) => (
          <p key={i} style={{ margin: '0 0 12px' }}>
            <strong>{m.role === 'user' ? 'You' : 'Cadre AI'}:</strong>{' '}
            <span style={{ color: m.isError ? '#b00' : 'inherit', whiteSpace: 'pre-wrap' }}>
              {m.content}
              {streaming && i === messages.length - 1 && m.role === 'assistant' && ' ▍'}
            </span>
          </p>
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={send} style={{ display: 'flex', gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about Cadre AI…"
          disabled={streaming}
          /* 16px minimum prevents iOS Safari zooming on focus (CLAUDE.md) */
          style={{ flex: 1, padding: 8, fontSize: 16 }}
        />
        <button type="submit" disabled={streaming || !input.trim()} style={{ padding: '8px 16px' }}>
          {streaming ? '…' : 'Send'}
        </button>
      </form>

      {firstTokenMs !== null && (
        <p style={{ fontSize: 12, color: '#666', marginTop: 8 }}>
          time to first token: {firstTokenMs}ms — if this is near the full response time, a proxy
          buffered the stream.
        </p>
      )}

      <p style={{ fontSize: 12, color: '#999', marginTop: 16 }}>
        Knowledge is limited to three facts in this phase. Anything else is routed to{' '}
        <a href="https://www.cadreai.com/contact">cadreai.com/contact</a>.
      </p>
    </main>
  )
}
