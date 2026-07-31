/**
 * The one place in the front end that knows the SSE wire format.
 *
 * ⚠️ **Found by a test, not by reading.** `test_there_is_exactly_one_sse_parser_in_the_codebase`
 * was written to stop the new widget growing its own reader, and it immediately reported that
 * `Playground.jsx` already had one — a byte-identical copy of the loop in `App.jsx` that had been
 * sitting there since Phase 9. The guard found a defect it was not aimed at.
 *
 * What is shared is the *wire format*: the response body arrives in arbitrary chunks, frames are
 * separated by a blank line, and a frame can be split across two reads. What is NOT shared is what
 * to do with each event — the chat accumulates deltas into a transcript and ignores `done`, the
 * playground shows a single answer and needs `done` for its metrics. Forcing both through one
 * state machine would distort it; forcing both through one *parser* is simply correct.
 *
 * Reads with `fetch` + `ReadableStream` rather than `EventSource`, because `EventSource` cannot
 * issue a POST and the conversation has to go in the request body.
 */
export async function readSseFrames(response, onEvent) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Frames are separated by a blank line. A frame can arrive split across reads, so only
    // consume complete ones and keep the remainder buffered — dropping it would silently lose
    // whichever delta happened to straddle a chunk boundary.
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      onEvent(JSON.parse(line.slice(6)))
    }
  }
}
