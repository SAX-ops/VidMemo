import { describe, it, expect } from 'vitest'
import {
  formatSRTTime,
  generateSRT,
  safeFilename,
  generateFullSummary,
  formatTime,
} from '../useExport'
import type { SubtitleSegment, OutlineSection, ExecutiveSummary } from '~/types'

describe('formatSRTTime', () => {
  it('formats 0 seconds', () => {
    expect(formatSRTTime(0)).toBe('00:00:00,000')
  })

  it('formats seconds with milliseconds', () => {
    expect(formatSRTTime(12.456)).toBe('00:00:12,456')
  })

  it('formats minutes and seconds', () => {
    expect(formatSRTTime(90)).toBe('00:01:30,000')
  })

  it('formats hours', () => {
    expect(formatSRTTime(3661.5)).toBe('01:01:01,500')
  })

  it('rounds milliseconds correctly', () => {
    expect(formatSRTTime(1.999)).toBe('00:00:01,999')
    expect(formatSRTTime(1.001)).toBe('00:00:01,001')
  })
})

describe('generateSRT', () => {
  it('generates SRT from segments', () => {
    const segments: SubtitleSegment[] = [
      { start: 0, end: 2.5, text: 'Hello world' },
      { start: 3, end: 5, text: 'Second line' },
    ]
    const result = generateSRT(segments)
    expect(result).toBe(
      '1\n00:00:00,000 --> 00:00:02,500\nHello world\n\n' +
      '2\n00:00:03,000 --> 00:00:05,000\nSecond line\n'
    )
  })

  it('returns empty string for empty segments', () => {
    expect(generateSRT([])).toBe('')
  })

  it('handles single segment', () => {
    const segments: SubtitleSegment[] = [
      { start: 10, end: 15, text: 'Only line' },
    ]
    const result = generateSRT(segments)
    expect(result).toContain('1\n')
    expect(result).toContain('00:00:10,000 --> 00:00:15,000')
    expect(result).toContain('Only line')
  })
})

describe('safeFilename', () => {
  it('sanitizes special characters', () => {
    expect(safeFilename('Test: Video <Title>')).toBe('Test_ Video _Title_')
  })

  it('returns "video" for undefined', () => {
    expect(safeFilename(undefined)).toBe('video')
  })

  it('returns "video" for empty string', () => {
    expect(safeFilename('')).toBe('video')
  })

  it('truncates long filenames to 80 chars', () => {
    const long = 'A'.repeat(100)
    expect(safeFilename(long).length).toBe(80)
  })

  it('preserves safe characters', () => {
    expect(safeFilename('My Video 2026')).toBe('My Video 2026')
  })
})

describe('formatTime', () => {
  it('formats under 1 hour', () => {
    expect(formatTime(90)).toBe('1:30')
  })

  it('formats over 1 hour', () => {
    expect(formatTime(3661)).toBe('1:01:01')
  })

  it('formats zero', () => {
    expect(formatTime(0)).toBe('0:00')
  })

  it('pads single digit seconds', () => {
    expect(formatTime(5)).toBe('0:05')
  })
})

describe('generateFullSummary', () => {
  const formatFn = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

  it('returns empty for empty outline', () => {
    expect(generateFullSummary([], null, undefined, formatFn)).toBe('')
  })

  it('includes video title as h1', () => {
    const outline: OutlineSection[] = [
      { title: 'Intro', timestamp: 0, summary: [] },
    ]
    const result = generateFullSummary(outline, null, 'My Video Title', formatFn)
    expect(result).toContain('# My Video Title')
  })

  it('includes executive summary with all fields', () => {
    const outline: OutlineSection[] = [
      { title: 'Intro', timestamp: 0, summary: ['Point A'] },
    ]
    const exec: ExecutiveSummary = {
      core_topic: 'AI Development',
      key_insights: ['Insight 1', 'Insight 2'],
      author_conclusion: 'AI is great',
      controversies: ['Controversial take'],
    }
    const result = generateFullSummary(outline, exec, 'Video', formatFn)
    expect(result).toContain('## 视频概述')
    expect(result).toContain('**核心主题：** AI Development')
    expect(result).toContain('**关键观点：**')
    expect(result).toContain('- Insight 1')
    expect(result).toContain('- Insight 2')
    expect(result).toContain('**作者结论：** AI is great')
    expect(result).toContain('**争议与讨论：**')
    expect(result).toContain('- ⚡ Controversial take')
  })

  it('skips empty executive summary fields', () => {
    const outline: OutlineSection[] = [
      { title: 'Intro', timestamp: 0, summary: [] },
    ]
    const exec: ExecutiveSummary = {
      core_topic: '',
      key_insights: [],
      author_conclusion: '',
      controversies: [],
    }
    const result = generateFullSummary(outline, exec, 'Video', formatFn)
    expect(result).not.toContain('## 视频概述')
    expect(result).toContain('## 视频大纲')
  })

  it('includes outline with timestamps and bullets', () => {
    const outline: OutlineSection[] = [
      { title: 'Introduction', timestamp: 0, summary: ['Welcome', 'Overview'] },
      { title: 'Main Content', timestamp: 120, summary: ['Details'] },
    ]
    const result = generateFullSummary(outline, null, undefined, formatFn)
    expect(result).toContain('## 视频大纲')
    expect(result).toContain('### 0:00 Introduction')
    expect(result).toContain('- Welcome')
    expect(result).toContain('- Overview')
    expect(result).toContain('### 2:00 Main Content')
    expect(result).toContain('- Details')
  })

  it('works with only outline (no title, no exec summary)', () => {
    const outline: OutlineSection[] = [
      { title: 'Chapter 1', timestamp: 0, summary: [] },
    ]
    const result = generateFullSummary(outline, null, undefined, formatFn)
    expect(result).toContain('## 视频大纲')
    expect(result).toContain('### 0:00 Chapter 1')
    expect(result.split('\n').filter(l => l.startsWith('# ') && !l.startsWith('## ')).length).toBe(0)
  })

  it('skips empty summary arrays in outline', () => {
    const outline: OutlineSection[] = [
      { title: 'Empty', timestamp: 0, summary: [] },
    ]
    const result = generateFullSummary(outline, null, undefined, formatFn)
    expect(result).toContain('### 0:00 Empty')
    expect(result).not.toContain('- ')
  })
})
