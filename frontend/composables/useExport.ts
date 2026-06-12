import type { SubtitleSegment, OutlineSection, ExecutiveSummary } from '~/types'

/**
 * Format seconds to SRT timestamp: HH:MM:SS,mmm
 */
export function formatSRTTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  const ms = Math.round((seconds % 1) * 1000)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`
}

/**
 * Generate SRT subtitle file content from segments.
 */
export function generateSRT(segments: SubtitleSegment[]): string {
  return segments.map((seg, i) => {
    const start = formatSRTTime(seg.start)
    const end = formatSRTTime(seg.end)
    return `${i + 1}\n${start} --> ${end}\n${seg.text}\n`
  }).join('\n')
}

/**
 * Sanitize a video title into a safe filename (no special chars).
 */
export function safeFilename(title: string | undefined): string {
  if (!title) return 'video'
  return title.replace(/[<>:"/\\|?*]/g, '_').substring(0, 80)
}

/**
 * Generate complete markdown export from all available summary data.
 * Includes: video title, executive summary, and chapter outline.
 * Always produces useful output as long as outline exists.
 */
export function generateFullSummary(
  outline: OutlineSection[],
  executiveSummary: ExecutiveSummary | null,
  videoTitle: string | undefined,
  formatTime: (s: number) => string,
): string {
  if (!outline.length) return ''
  const lines: string[] = []

  // Video title
  if (videoTitle) {
    lines.push(`# ${videoTitle}`, '')
  }

  // Executive summary section
  if (executiveSummary) {
    const hasContent =
      executiveSummary.core_topic ||
      executiveSummary.key_insights?.length ||
      executiveSummary.author_conclusion ||
      executiveSummary.controversies?.length

    if (hasContent) {
      lines.push('## 视频概述', '')
      if (executiveSummary.core_topic) {
        lines.push(`**核心主题：** ${executiveSummary.core_topic}`, '')
      }
      if (executiveSummary.key_insights?.length) {
        lines.push('**关键观点：**')
        for (const item of executiveSummary.key_insights) {
          lines.push(`- ${item}`)
        }
        lines.push('')
      }
      if (executiveSummary.author_conclusion) {
        lines.push(`**作者结论：** ${executiveSummary.author_conclusion}`, '')
      }
      if (executiveSummary.controversies?.length) {
        lines.push('**争议与讨论：**')
        for (const item of executiveSummary.controversies) {
          lines.push(`- ⚡ ${item}`)
        }
        lines.push('')
      }
    }
  }

  // Chapter outline
  lines.push('## 视频大纲', '')
  for (const sec of outline) {
    lines.push(`### ${formatTime(sec.timestamp)} ${sec.title}`)
    if (sec.summary?.length) {
      for (const item of sec.summary) {
        lines.push(`- ${item}`)
      }
    }
    lines.push('')
  }

  return lines.join('\n')
}

/**
 * Format seconds to display time (M:SS or H:MM:SS).
 */
export function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}
