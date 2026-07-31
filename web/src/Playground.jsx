import { useEffect, useRef, useState } from 'react'

import { renderInline } from './markdown.jsx'

/**
 * The playground tab: run one turn and see what it actually cost.
 *
 * Every number here already existed — the `done` frame carries the token counters, status,
 * refusal_reason and now cost/latency; the chat tab has always timed first-token and thrown the
 * value away. This is presentation over existing instrumentation, not new measurement.
 *
 * ⚠️ `cost_usd` comes from the server. Recomputing it in JS would be a second implementation of the
 * four-rate cache maths, and the point of app/obs/cost.py is that there is exactly one.
 *
 * ⚠️ The system prompt is NOT shown and no endpoint returns it. Publishing it would publish the
 * refusal-marker syntax, which a user message could then inject to fake or suppress a refusal.
 * Only metadata — version, size, margin over the cache floor — is displayed.
 *
 * Single-turn by design: each run starts fresh, so the numbers describe one turn rather than an
 * accumulating conversation. Multi-turn behaviour is the chat tab's job.
 */
export default function Playground({ config }) {
  const [input, setInput] = useState('')
  const [answer, setAnswer] = useState('')
  const [meta, setMeta] = useState(null)
  const [running, setRunning] = useState(false)
  const endRef = useRef(null)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    endRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' })
  }, [answer, meta])

  async function run(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || running) return

    setAnswer('')
    setMeta(null)
    setRunning(true)

    const started = performance.now()
    let firstTokenMs = null

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [{ role: 'user', content: text }] }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          const line = frame.split('\n').find((l) => l.startsWith('data: '))
          if (!line) continue
          const evt = JSON.parse(line.slice(6))

          if (evt.type === 'delta') {
            if (firstTokenMs === null) firstTokenMs = Math.round(performance.now() - started)
            setAnswer((a) => a + evt.text)
          } else if (evt.type === 'done') {
            setMeta({ ...evt, firstTokenMs })
          } else if (evt.type === 'error') {
            setAnswer(evt.text)
            setMeta({ error: true, reason: evt.reason, request_id: evt.request_id, firstTokenMs })
          }
        }
      }
    } catch (err) {
      setAnswer(`Couldn't reach the server (${err.message}).`)
      setMeta({ error: true })
    } finally {
      setRunning(false)
    }
  }

  const u = meta?.usage
  // A write is the first turn of a 5-minute TTL window and costs ~5x a read. Saying which one
  // happened teaches more about this system than the raw counters do.
  const cacheKind = u
    ? u.cache_creation_input_tokens > 0
      ? 'write — first turn of a TTL window, ~5× a read'
      : u.cache_read_input_tokens > 0
        ? 'read — prefix was still warm'
        : 'none — prefix did not cache'
    : null

  return (
    <div className="pg">
      {config && (
        <p className="pg-strip">
          {config.model} · prompt v{config.prompt?.version} · {fmt(config.prompt?.tokens)} tokens ·{' '}
          {fmt(config.prompt?.margin_over_floor)} over the {fmt(config.prompt?.cache_floor_tokens)}{' '}
          cache floor · corpus {config.corpus?.sha256}
        </p>
      )}

      <form className="composer" onSubmit={run}>
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything — see what the turn cost…"
          disabled={running}
          aria-label="Playground question"
        />
        <button className="send" type="submit" disabled={running || !input.trim()}>
          {running ? '…' : 'Run'}
        </button>
      </form>

      <div className="transcript" role="log" aria-live="polite" aria-label="Playground answer">
        {!answer && !running && <p className="empty">Run a turn to see its tokens, cost and latency.</p>}
        <p className={meta?.error ? 'message message--error' : 'message'}>
          {meta?.error ? answer : renderInline(answer)}
          {running && <span className="caret">▍</span>}
        </p>
        <div ref={endRef} />
      </div>

      {meta && !meta.error && (
        <dl className="pg-metrics">
          <Row label="status">
            {meta.status}
            {meta.refusal_reason ? ` · ${meta.refusal_reason}` : ''}
            {meta.stop_reason ? ` · ${meta.stop_reason}` : ''}
          </Row>
          <Row label="tokens">
            in {fmt(u?.input_tokens)} · out {fmt(u?.output_tokens)} · cache write{' '}
            {fmt(u?.cache_creation_input_tokens)} · read {fmt(u?.cache_read_input_tokens)}
          </Row>
          <Row label="prompt read">
            {fmt(u?.total_prompt_tokens)} tokens — what the model actually read, cached portion
            included
          </Row>
          <Row label="cache">{cacheKind}</Row>
          <Row label="cost">${meta.cost_usd?.toFixed(7)}</Row>
          <Row label="latency">
            first token {fmt(meta.firstTokenMs)} ms · total {fmt(meta.latency_ms)} ms
          </Row>
          <Row label="request">{meta.request_id}</Row>
        </dl>
      )}

      {meta?.error && meta.reason && (
        <dl className="pg-metrics">
          <Row label="rejected">{meta.reason}</Row>
          <Row label="request">{meta.request_id}</Row>
        </dl>
      )}
    </div>
  )
}

function Row({ label, children }) {
  return (
    <>
      <dt className="pg-key">{label}</dt>
      <dd className="pg-val">{children}</dd>
    </>
  )
}

const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('en-US') : '—')
