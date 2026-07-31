import { useState } from 'react'

/**
 * The conversation engine, shared by every surface that talks to the bot.
 *
 * Extracted from `App.jsx` when the floating widget arrived. **The point of extracting it is that
 * there must only ever be ONE SSE parser.** A copied one would drift, and the two things most
 * likely to drift are the frame-buffering and the shape of the `done` frame — both of which have
 * already changed twice in this project's life.
 *
 * Reads the SSE body with `fetch` + `ReadableStream` rather than `EventSource`, because
 * `EventSource` cannot issue a POST and the conversation has to go in the request body.
 *
 * ⚠️ **`send` is behaviour under test, not layout.** It accumulates only the visible delta text
 * into the assistant turn and posts the whole array back, and multi-turn correctness depends on
 * both halves — the refusal marker is stripped server-side, so storing raw frames instead would put
 * it into history and undo Phase 4. Style the components freely; leave this loop alone.
 *
 * Returns plain state and one action. It renders nothing and knows nothing about which surface is
 * using it, which is what lets the full page and the widget share it without either importing the
 * other.
 */
export function useChat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [firstTokenMs, setFirstTokenMs] = useState(null)

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

  return { messages, input, setInput, send, streaming, firstTokenMs }
}
