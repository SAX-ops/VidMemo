# AI Video Summary — Design Spec

**Date:** 2026-06-07
**Status:** Design — awaiting user approval
**Scope:** Add AI-powered video summarization to VidSumAI, initially supporting YouTube and Bilibili (B站)

---

## 1. Background & Goal

VidSumAI currently lets users parse, preview, and download videos from 9 platforms. Users want to **learn faster from video content** by:

- Getting a text summary instead of watching a 1-hour lecture
- Jumping directly to the moments that matter (timestamped chapters)
- Seeing a visual outline of the video's key points (mind map — deferred to next iteration)

This design adds an **AI video summary module** alongside the existing download flow. Mind map generation is explicitly **out of MVP scope** (deferred per user decision) — the module is architected so it can be added later without refactoring.

### Competitive context

Three competitors were surveyed (`bibigpt.co`, `notegpt.io/cn/bilibili-summarizer`, `eightify.app`). Key takeaways:

- All three rely on **platform-provided subtitles** (manual or auto) — none solve the no-subtitle problem in a general way
- BibiGPT (1M+ users) and the open-source `liyupi/free-video-downloader` (which the spec largely mirrors) use a **4-section summary template** (视频概述 / 内容大纲 / 核心知识要点 / 总结) with chapter-level timestamps
- Streaming the summary token-by-token (SSE) is the standard UX pattern; full-page spinners are considered bad
- None of the three offer **download + summary** as a unified experience — this is VidSumAI's natural moat

### Non-goals (explicit)

- ❌ Mind map / 思维导图 rendering (deferred; markmap dependency may still be pre-installed for next iteration)
- ❌ AI chat / 问答 over video content (deferred)
- ❌ Platforms other than YouTube and B站 in MVP (TikTok, 抖音, Instagram, 微博, X, Facebook, 小红书)
- ❌ ASR / speech-to-text for videos without subtitles (whisper.cpp integration)
- ❌ Login, payment, quota, or any user-account system
- ❌ Top-comment analysis (Eightify's differentiator)

---

## 2. Architecture

```
┌──────────────┐   POST /api/summarize   ┌──────────────────────┐
│   前端 UI    │ ◀────── SSE 流式 ────── │  routers/summary.py  │
│  index.vue + │                         │   ├─ SubtitleExt.    │
│ VideoSummary │                         │   │  (B站 dm/view +   │
│   .vue)      │ ── 章节跳转 (mm:ss) ──▶ │   │   yt-dlp VTT)     │
└──────────────┘                         │   └─ VideoSummarizer │
        │                                │      (OpenAI 兼容)   │
        ▼                                └──────────────────────┘
  VideoPreview                                            │
  (setCurrentTime)                                        ▼
                                                Claude / GPT API
                                                (环境变量配置)
```

### Key design choices

- **Independent service**: AI summary is its own router + service module. It does **not** depend on the existing `/api/parse` results — it re-fetches video info internally. This keeps the download flow and summary flow decoupled.
- **Reuse `VideoPreview` for playback**: chapter clicks call `videoPreviewRef.value.setCurrentTime(t)` to jump. No new player needed.
- **SSE (not WebSocket)**: summary is a unidirectional server→client stream. The existing WebSocket stays for download progress — they don't conflict.
- **OpenAI-compatible client**: use the `openai` Python SDK with a configurable `base_url`. This works for OpenAI, Anthropic (via proxy), DeepSeek, and any other OpenAI-protocol-compatible provider.

---

## 3. Backend Design

### 3.1 New files

```
backend/
├── services/
│   └── summarizer.py           # SubtitleExtractor + VideoSummarizer
├── routers/
│   └── summary.py              # POST /api/summarize (SSE)
├── models.py                   # + SubtitleSegment, SubtitleData, SummarizeRequest
├── tests/
│   └── test_summarizer.py      # Unit tests
├── pyproject.toml              # + openai, httpx (httpx already present)
└── .env.example                # + OPENAI_API_KEY, SUMMARY_MODEL
```

### 3.2 `SubtitleExtractor`

Mirrors the reference implementation in `liyupi/free-video-downloader/backend/summarizer.py:18`. Behavior:

| Input | Path |
|---|---|
| Bilibili URL (detected by `bilibili.com` or `b23.tv` in URL) | Direct HTTP calls to `api.bilibili.com/x/web-interface/view` and `x/v2/dm/view` to fetch CC subtitles. Parses `subtitle.body[]` JSON. |
| Other platforms | `yt_dlp.YoutubeDL` with `writesubtitles=True, writeautomaticsub=True, subtitlesformat="vtt", skip_download=True`. Parses the resulting `.vtt` file via regex. |

Subtitle selection priority:
1. Manual subtitles, in order: `zh-Hans > zh > zh-CN > en > ja > ko`
2. Auto-generated subtitles, same language order
3. Any other manual subtitle
4. Any other auto subtitle
5. Empty result

Output shape (`SubtitleData`):
```python
{
  "has_subtitle": bool,
  "language": str,             # e.g. "zh-Hans"
  "subtitle_type": str,        # "manual" | "auto" | "none"
  "segments": [{"start": float, "end": float, "text": str}, ...],
  "full_text": str,            # space-joined segment texts
}
```

`full_text` is **truncated to 15 000 chars** before being sent to the LLM, to keep token cost predictable.

### 3.3 `VideoSummarizer`

Constructed lazily (singleton) so that the LLM client is only created on first request, not at app startup. Configuration is via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | (required) | API key for the LLM provider |
| `ANTHROPIC_API_KEY` | (optional) | If set, used with `base_url` pointing to Anthropic's OpenAI-compat endpoint |
| `SUMMARY_MODEL` | `gpt-4o-mini` | Model name to send in the request |
| `SUMMARY_BASE_URL` | (optional) | Override OpenAI-compatible `base_url` (for proxies or DeepSeek) |

Three methods:

- `summarize_stream(subtitle_text, language) -> Iterator[str]` — yields summary tokens
- `generate_mindmap(subtitle_text, language) -> str` — non-streaming, returns markdown (NOT used in MVP but kept for the next iteration to avoid a refactor)
- `chat_stream(subtitle_text, question) -> Iterator[str]` — RAG-style Q&A (NOT used in MVP, same reason)

The `_build_*_prompt` static methods are kept as in the reference.

### 3.4 Prompt template (4-section, with chapter timestamps)

```
请对以下视频字幕内容进行深度总结分析，使用{lang}输出。

要求输出格式：

## 视频概述
（用 2-3 句话概括视频的主题和核心内容）

## 内容大纲
（按视频内容的逻辑顺序，列出主要章节/段落。
 每个章节标题必须以 mm:ss 格式的时间戳开头，
 例如 "### 01:23 GPT 的核心机制"。最多 6-8 个章节。）

## 核心知识要点
（提取视频中最重要的知识点、观点或结论，用编号列表形式。最多 8 条。）

## 总结
（用 1-2 句话给出整体评价或一句话总结）

---
视频字幕内容：
{truncated_subtitle}
```

`{lang}` is `中文` if `language.startswith("zh")` else the same language as the subtitle.

The chapter timestamps are **the contract** between the LLM and the frontend: the frontend parses any `### mm:ss` line at the start of a heading and turns it into a clickable chapter link.

### 3.5 API: `POST /api/summarize`

**Request** (`application/json`):
```json
{ "url": "https://www.youtube.com/watch?v=...", "language": "zh" }
```

**Response**: `text/event-stream` (SSE), event types:

| Event | Payload | When |
|---|---|---|
| `subtitle` | JSON `SubtitleData` | After subtitle extraction, before summarization |
| `summary` | JSON string (single token) | Per LLM token, streamed |
| `done` | `[DONE]` literal | Stream end (success) |
| `error` | JSON `{ "message": str, "code": str }` | Any failure point |

The `subtitle` event is sent first so the frontend can render the raw subtitles tab immediately, then `summary` tokens stream in. This is the same protocol as the reference project.

Implementation uses FastAPI's `EventSourceResponse` and `loop.run_in_executor` to call blocking yt-dlp code without freezing the event loop — the same pattern used in the existing `YtdlpService`.

### 3.6 Error handling

| Scenario | HTTP / SSE | User-facing message |
|---|---|---|
| `OPENAI_API_KEY` not set | SSE `error` (500) | "AI 总结功能未配置：缺少 OPENAI_API_KEY 环境变量" |
| Invalid URL / unsupported platform | SSE `error` (400) | "不支持的视频链接" |
| No subtitle available | SSE `error` (422) | "该视频没有可用的字幕，无法生成总结" |
| yt-dlp fails to fetch subtitles | SSE `error` (502) | "无法获取字幕：{underlying reason}" |
| LLM call fails | SSE `error` (502) | "AI 总结服务暂时不可用，请稍后重试" |
| LLM call exceeds 60 s | SSE `error` (504) | "AI 总结超时，请重试或换一个较短的字幕" |
| Private / deleted video | SSE `error` (404) | "视频不可访问" |

All errors arrive as SSE `event: error` — the HTTP status stays 200 because the *request* succeeded; the *operation* failed inside the stream.

### 3.7 Configuration

`pyproject.toml` dependency addition (run `uv add openai`):
```toml
"openai>=1.0.0",
```

`httpx>=0.28.1` is already a dependency.

`.env.example`:
```bash
# AI Summary (optional; required for /api/summarize to work)
OPENAI_API_KEY=sk-xxx
SUMMARY_MODEL=gpt-4o-mini
# SUMMARY_BASE_URL=https://api.deepseek.com   # uncomment to use DeepSeek
```

---

## 4. Frontend Design

### 4.1 New / changed files

```
frontend/
├── components/
│   ├── VideoSummary.vue       # NEW — summary panel, dark-theme adapted
│   └── VideoPreview.vue       # MODIFIED — expose setCurrentTime via defineExpose
├── composables/
│   └── useSSE.ts              # NEW — fetch + ReadableStream SSE client
├── pages/
│   └── index.vue              # MODIFIED — add "AI 总结" button + panel mount
├── types/
│   └── index.ts               # MODIFIED — add SubtitleData, SubtitleSegment
└── package.json               # + marked (new dep)
```

### 4.2 Interaction flow

```
[粘贴 URL] → [解析视频] → [预览视频] (VideoPreview 已显示)
                          ↓
              ┌───────────┴───────────┐
              │                       │
         [下载到本地]            [AI 总结]   ← new button
              │                       │
              ▼                       ▼
       (existing flow)    ┌──────────────────────┐
                           │   VideoSummary.vue   │
                           │  ┌────────────────┐  │
                           │  │ 总结摘要 (active)│  │  ← marked.js
                           │  │ 字幕文本          │  │  ← segments
                           │  │ 思维导图 (locked) │  │  ← next iter
                           │  │ AI 问答 (locked)  │  │  ← next iter
                           │  └────────────────┘  │
                           └──────────────────────┘
                                       │
                       click "### 01:23 GPT 的核心机制"
                                       │
                                       ▼
                       videoPreviewRef.value.setCurrentTime(83)
                                       │
                                       ▼
                           video.currentTime = 83
```

### 4.3 `VideoSummary.vue`

Direct port of `liyupi/free-video-downloader/frontend/src/components/VideoSummary.vue` with these adaptations:

- **Tabs**: keep 4 tabs in the markup (so the next iteration is a UI toggle, not a refactor) but only render content for `summary` and `subtitle`. `mindmap` and `qa` tabs show a "下一迭代" placeholder.
- **Dark theme**: replace white surfaces with VidSumAI's `dark-bg` / `dark-card` / `primary-from-to` Tailwind colors. Reuse the typography from `index.vue`.
- **Chapter click**: after `marked.parse(summary)`, walk the rendered HTML and add `data-timestamp` to any heading starting with `mm:ss`. Bind a click handler that calls `emit('chapter-click', t)`.
- **Quota UI removed**: the reference's daily-quota banner and "升级 VIP" button are dropped — this is a local tool, not a SaaS.

Props / emits:
```ts
defineProps<{ videoUrl: string; videoTitle?: string }>()
defineEmits<{
  'chapter-click': [timeSec: number]  // bubbles to index.vue → VideoPreview.setCurrentTime
  'loading-change': [loading: boolean]
}>()
```

The component auto-starts summarization on `onMounted` (same as the reference). It does not block other UI — the loading spinner lives inside the panel.

### 4.4 `useSSE.ts`

```ts
export function useSSE<T = unknown>(url: string, body: unknown, callbacks: {
  [event: string]: (data: T) => void
}): Promise<void>
```

Thin wrapper around `fetch` + `ReadableStream` that parses the SSE wire format (`event:` and `data:` lines separated by blank lines). Same shape as `useWebSocket` so consumers feel familiar.

### 4.5 `VideoPreview.vue` modification

Add a single `defineExpose` block:
```ts
defineExpose({
  play: () => video.value?.play(),
  pause: () => video.value?.pause(),
  setCurrentTime: (t: number) => { if (video.value) video.value.currentTime = t },
  getCurrentTime: () => video.value?.currentTime ?? 0,
})
```

The existing internal `currentTime` ref stays as-is — it just gets read externally now. No new state, no new behavior, no risk of breaking the existing preview flow.

### 4.6 `index.vue` integration

- Keep a `ref<InstanceType<typeof VideoPreview> | null>(null)` (`videoPreviewRef`).
- After parse succeeds, render **two** action buttons next to the quality selector:
  - Existing `[下载到本地]` (unchanged)
  - New `[AI 总结]` — toggles `showSummaryPanel` ref
- When `showSummaryPanel` is true, render `<VideoSummary :video-url="..." @chapter-click="onChapterClick" />` in a new section below `VideoPreview`.
- `onChapterClick(t)`: `videoPreviewRef.value?.setCurrentTime(t)` and ensure the preview is playing if the user clicked expecting playback to start.

The summary panel is mounted only after first click (v-if), so the LLM token stream is not requested until the user actually wants it.

---

## 5. Data Contracts (TypeScript)

```ts
// frontend/types/index.ts (additions)
export interface SubtitleSegment {
  start: number   // seconds
  end: number
  text: string
}

export interface SubtitleData {
  has_subtitle: boolean
  language: string
  subtitle_type: 'manual' | 'auto' | 'none'
  segments: SubtitleSegment[]
  full_text: string
}
```

```python
# backend/models.py (additions)
class SubtitleSegment(BaseModel):
    start: float
    end: float
    text: str

class SubtitleData(BaseModel):
    has_subtitle: bool
    language: str = ""
    subtitle_type: str = "none"  # "manual" | "auto" | "none"
    segments: list[SubtitleSegment] = []
    full_text: str = ""

class SummarizeRequest(BaseModel):
    url: str
    language: str = "zh"
```

---

## 6. Testing Strategy

### 6.1 Backend unit tests (`tests/test_summarizer.py`)

| Test | What it verifies |
|---|---|
| `test_bilibili_url_detection` | `_is_bilibili_url` matches `bilibili.com` and `b23.tv` |
| `test_vtt_parser_simple` | `_parse_vtt` extracts segments from a known VTT string |
| `test_vtt_parser_dedup` | duplicate consecutive lines are removed |
| `test_subtitle_priority_manual_first` | manual subs beat auto subs at same language |
| `test_subtitle_priority_lang_order` | `zh-Hans` beats `en` beats `ja` |
| `test_full_text_truncation` | `full_text` is capped at 15 000 chars |
| `test_prompt_contains_timestamps_instruction` | prompt template includes the chapter-timestamp instruction |
| `test_summarizer_requires_api_key` | `VideoSummarizer()` raises if `OPENAI_API_KEY` is unset |
| `test_summarize_endpoint_sends_subtitle_event_first` | using `httpx.AsyncClient` + `EventSource`-like parser against a stubbed service, verify event order |

The LLM call itself is **not** unit-tested (no live API in CI). The `VideoSummarizer` is tested with a fake `OpenAI` client that returns canned streaming chunks.

### 6.2 Backend integration test (manual)

Documented in `docs/superpowers/plans/2026-06-07-ai-video-summary.md` (the implementation plan) as a manual smoke test:

```bash
# Terminal 1
cd backend && OPENAI_API_KEY=sk-xxx uv run python -m uvicorn main:app --port 8000

# Terminal 2
curl -N -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

Expect: `subtitle` event with `has_subtitle: true`, then a stream of `summary` tokens, then `done`. Errors return `error` event with a friendly message.

### 6.3 Frontend tests

No new e2e tests in this iteration (the existing Playwright suite covers `VideoPreview`; adding summary e2e would require a real LLM key in CI). The summary panel is exercised manually as part of acceptance.

### 6.4 Acceptance checklist

- [ ] YouTube video with subtitles → summary streams in, 4 sections visible, at least 3 chapter timestamps clickable
- [ ] Clicking a chapter jumps the video to within 1 s of the timestamp
- [ ] B站 video with CC subtitles → same flow works (test with a known B站 URL)
- [ ] YouTube video without subtitles (e.g. a music video) → friendly error, no crash
- [ ] LLM call taking > 60 s → 504-style error message, button re-enabled
- [ ] `OPENAI_API_KEY` unset → backend startup logs a clear warning, request returns SSE error
- [ ] Dark theme matches `index.vue` (no light-mode leaks)
- [ ] Existing download flow is unchanged (regression check: parse → preview → download still works for all 9 platforms)

---

## 7. Out of Scope (Explicit)

These are intentionally **not** part of this design. They are listed here so future readers know they were considered:

- **Mind map rendering** — `markmap-lib` + `markmap-view` are not in `package.json` and **will not be added in MVP**. The `VideoSummary.vue` UI keeps the `mindmap` tab in markup as a placeholder (renders "下一迭代" text), so adding the dependency + real rendering later is a non-breaking change.
- **AI Q&A** — same reason. The `chat` method on `VideoSummarizer` exists in code (mirroring the reference) but is not exposed via API or UI.
- **Platforms without subtitles** — TikTok, 抖音, Instagram, 微博, X, Facebook, 小红书. Adding these requires ASR (whisper.cpp or cloud) which is a separate spec.
- **User accounts, quota, payment** — this is a local tool; the LLM cost is borne by whoever holds the API key (likely the dev who runs the backend).
- **Comment analysis** — Eightify's differentiator. Could be added later.
- **Vision-based understanding** (BibiGPT's slide/frame analysis) — requires multimodal models and frame extraction, separate spec.

---

## 8. Open Questions

None blocking. Tracked in the implementation plan:

- Should `SUMMARY_MODEL` default to `gpt-4o-mini` (cheaper, faster) or `gpt-4o` (higher quality)? → Default `gpt-4o-mini`; user can override via env.
- Should the summary panel auto-collapse on chapter click? → No, user may want to read more after jumping.
- Should we cache summaries per URL? → Defer; out of MVP scope. Same URL clicked twice re-summarizes (acceptable, and LLM cost is the user's).

---

## 9. References

- Competitive research: `.firecrawl/{bibigpt-home,notegpt-bilibili,eightify-home}.md`
- Reference implementation: `github.com/liyupi/free-video-downloader` (cloned to `/tmp/free-video-downloader` for analysis)
- Existing architecture: [`docs/superpowers/specs/2026-04-25-vidsumai-design.md`](2026-04-25-vidsumai-design.md)
- Existing CLAUDE.md: project conventions for backend services, frontend components, tests
