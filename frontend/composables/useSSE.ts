/**
 * SSE client using fetch + ReadableStream.
 *
 * Returns an object with an `abort()` function. Wire format is parsed
 * from the standard SSE event-stream format (event: / data: lines
 * separated by blank lines).
 *
 * Usage:
 *   const { abort } = useSSE('/api/summarize', { url, language }, {
 *     subtitle: (data) => { ... },
 *     summary: (data) => { ... },
 *     chapters: (data) => { ... },
 *     done: () => { ... },
 *     error: (data) => { ... },
 *   })
 *   // later: abort()
 */

export interface SseCallbacks {
  [event: string]: (data: unknown) => void
}

export function useSSE(
  url: string,
  body: unknown,
  callbacks: SseCallbacks
): { abort: () => void } {
  const controller = new AbortController()

  const dispatch = async () => {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok) {
        callbacks.error?.({ message: `HTTP ${response.status}` })
        return
      }
      if (!response.body) {
        callbacks.error?.({ message: 'No response body' })
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''
      let dataLines: string[] = []
      let hasData = false

      const fire = () => {
        if (hasData && currentEvent) {
          const handler = callbacks[currentEvent]
          const raw = dataLines.join('\n')
          if (handler) {
            try {
              handler(JSON.parse(raw))
            } catch {
              handler(raw)
            }
          }
        }
        currentEvent = ''
        dataLines = []
        hasData = false
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line === '') {
            fire()
            continue
          }
          if (line.startsWith(':')) continue
          const colonIdx = line.indexOf(':')
          if (colonIdx < 0) continue
          const field = line.slice(0, colonIdx)
          let val = line.slice(colonIdx + 1)
          if (val.startsWith(' ')) val = val.slice(1)
          if (field === 'event') {
            currentEvent = val
          } else if (field === 'data') {
            hasData = true
            dataLines.push(val)
          }
        }
      }
      fire()
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        return  // user-initiated abort, no error
      }
      callbacks.error?.({ message: err?.message || String(err) })
    }
  }

  dispatch()

  return {
    abort: () => controller.abort(),
  }
}
