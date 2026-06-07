const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'

export interface FormatInfo {
  quality: string
  ext: string
  size: number | null
  url: string
  audio_url?: string
}

export interface VideoInfo {
  title: string
  thumbnail: string
  duration: number | null
  platform: string
  url: string
  max_quality: string
  formats: FormatInfo[]
}

export async function healthCheck(): Promise<boolean> {
  try {
    const r = await fetch(`${BACKEND}/health`)
    return r.ok
  } catch {
    return false
  }
}

export async function parseUrl(url: string): Promise<VideoInfo> {
  const r = await fetch(`${BACKEND}/api/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!r.ok) {
    const detail = await r.text()
    throw new Error(`parseUrl failed (${r.status}): ${detail}`)
  }
  return (await r.json()) as VideoInfo
}
