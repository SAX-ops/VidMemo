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

export interface ProgressUpdate {
  status: string
  progress: number
  speed: string
  eta: string
  downloaded: string
}

export interface DownloadState {
  url: string
  parsing: boolean
  downloading: boolean
  videoInfo: VideoInfo | null
  selectedQuality: string
  progress: ProgressUpdate | null
  error: string | null
}

export interface SubtitleSegment {
  start: number
  end: number
  text: string
}

export interface SubtitleData {
  has_subtitle: boolean
  language: string
  subtitle_type: 'manual' | 'auto' | 'none'
  is_target_language: boolean
  fallback_mode?: 'metadata'
  segments: SubtitleSegment[]
  full_text: string
}

export interface OutlinePart {
  timestamp: number
  content: string
}

export interface OutlineSection {
  title: string
  timestamp: number
  summary: string[]
}

export interface OutlineData {
  outline: OutlineSection[]
}

export interface ExecutiveSummary {
  core_topic: string
  key_insights: string[]
  author_conclusion: string
  controversies: string[]
}

/**
 * Mind-map node returned by `POST /api/summarize` (event: mindmap).
 *
 * Tree shape:
 *   root (level 0, video core topic — string only, no node object)
 *     └─ children (level 1, chapters — one per outline chapter)
 *         └─ children (level 2, bullets — 1-8 per chapter)
 *             └─ children (level 3, always empty array)
 *
 * Timestamps are grafted server-side from the outline (the LLM never owns
 * them); leaves inherit their parent chapter's timestamp. See
 * `backend/services/summarizer.py::parse_mindmap`.
 */
export interface MindmapNode {
  title: string
  timestamp: number
  children: MindmapNode[]
}

export interface MindmapData {
  root: string
  children: MindmapNode[]
}

// ---------------------------------------------------------------------------
// Chat with Video
// ---------------------------------------------------------------------------

/** Chapter-level citation returned by POST /api/chat (event: chat_done). */
export interface Citation {
  chapter_title: string
  timestamp: number
}

/** A single message in the chat panel. */
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

/** Chat panel state machine. */
export type ChatStatus = 'idle' | 'generating' | 'success' | 'error' | 'cancelled'
