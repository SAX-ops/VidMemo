# AI Video Summary — Design Spec

**Date:** 2026-06-07
**Status:** Implemented — revision 4
**Scope:** Add AI-powered video summarization to VidSumAI, initially supporting YouTube and Bilibili (B站)

## Revision history

| Rev | Date | Changes |
|---|---|---|
| 1 | 2026-06-07 | Initial design |
| 2 | 2026-06-07 | Review revisions: (1) metadata fallback when no subtitles (§3.4.2, §3.6); (2) strict prompt with dynamic chapter count + structured JSON output (§3.4); (3) file-based summary cache, 30-day TTL (§3.8); (4) `setCurrentTime`/`play` expose checklist (§4.5); (5) subtitle language fallback with UI banner (§3.2, §4.3); (6) SSE connection abort on unmount + re-click (§4.3, §4.4); (7) LLM timeout raised to 90s, dynamic for long subs (§3.3); (8) auto-play on chapter click (§4.6); (9) `SUMMARY_MOCK=true` for offline dev (§3.9); (10) Bilibili visitor-mode limitations documented (§4.7) |
| 3 | 2026-06-07 | Review additions: (a) `onChapterClick` swallows `NotAllowedError` from `play()` (§4.6); (b) chapter JSON parse failure logs WARNING, not ERROR, and emits empty `chapters` without aborting the stream (§3.4.3); (c) `SUMMARY_MOCK_DELAY_MS` default 50ms, 0 for tests (§3.7, §3.9) |
| 4 | 2026-06-09 | Two-stage architecture + Executive Summary + info architecture redesign. See §3.10, §3.11, §4.8 |

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

- ❌ Mind map / 思维导图 rendering (deferred; markmap not added in MVP)
- ❌ AI chat / 问答 over video content (deferred)
- ❌ Platforms other than YouTube and B站 in MVP (TikTok, 抖音, Instagram, 微博, X, Facebook, 小红书)
- ❌ ASR / speech-to-text for videos without subtitles — but **metadata-based fallback summary is in scope** (see §3.4.2)
- ❌ Login, payment, quota, or any user-account system
- ❌ Top-comment analysis (Eightify's differentiator)

---

## 2. Architecture

```
┌──────────────┐   POST /api/summarize   ┌──────────────────────────┐
│   前端 UI    │ ◀────── SSE 流式 ────── │  routers/summary.py      │
│  index.vue + │                         │   ├─ Cache lookup        │
│ VideoSummary │                         │   ├─ SubtitleExt.        │
│   .vue)      │ ── 章节跳转 (mm:ss) ──▶ │   │  (B站 dm/view +       │
└──────────────┘                         │   │   yt-dlp VTT)         │
        │                                │   ├─ Metadata fallback   │
        ▼                                │   │  (无字幕时降级)        │
  VideoPreview                            │   └─ VideoSummarizer     │
  (setCurrentTime + play)                  │      (OpenAI 兼容)       │
                                          │      或 MockProvider     │
                                          └──────────────────────────┘
                                                          │
                                                          ▼
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
│   ├── summarizer.py           # SubtitleExtractor + VideoSummarizer + MockProvider
│   └── summary_cache.py        # File-based summary cache (TTL 30 days)
├── routers/
│   └── summary.py              # POST /api/summarize (SSE)
├── models.py                   # + SubtitleSegment, SubtitleData, SummarizeRequest, Chapter
├── tests/
│   ├── test_summarizer.py      # Unit tests
│   └── test_summary_cache.py   # Cache hit / expiry tests
├── summary_cache.json          # gitignored, auto-created on first cache write
├── pyproject.toml              # + openai
└── .env.example                # + OPENAI_API_KEY, SUMMARY_MODEL, SUMMARY_MOCK, ...
```

### 3.2 `SubtitleExtractor`

Mirrors the reference implementation in `liyupi/free-video-downloader/backend/summarizer.py:18`. Behavior:

| Input | Path |
|---|---|
| Bilibili URL (detected by `bilibili.com` or `b23.tv` in URL) | Direct HTTP calls to `api.bilibili.com/x/web-interface/view` and `x/v2/dm/view` to fetch CC subtitles. Parses `subtitle.body[]` JSON. |
| Other platforms | `yt_dlp.YoutubeDL` with `writesubtitles=True, writeautomaticsub=True, subtitlesformat="vtt", skip_download=True`. Parses the resulting `.vtt` file via regex. |

Subtitle selection priority (target = Chinese by default):
1. Manual subtitles in **target language**, in order: `zh-Hans > zh > zh-CN`
2. Auto-generated subtitles in target language
3. Manual subtitles in **any other language** (e.g. `en`, `ja`, `ko`) — flagged `is_target_language: false` so the UI can warn "字幕为原始语言"
4. Auto-generated subtitles in any other language
5. Empty result

The target language is whatever the user requests in `SummarizeRequest.language` (default `"zh"`). When the chosen subtitle is not in the target language, the `SubtitleData` response carries an `is_target_language: false` flag and the prompt instructs the LLM to summarize in that language (not force-translate). The frontend shows a banner like "字幕为英文，已按原文总结".

Output shape (`SubtitleData`):
```python
{
  "has_subtitle": bool,
  "language": str,             # e.g. "zh-Hans" or "en"
  "subtitle_type": str,        # "manual" | "auto" | "none"
  "is_target_language": bool,  # NEW — false when target lang unavailable
  "segments": [{"start": float, "end": float, "text": str}, ...],
  "full_text": str,            # space-joined segment texts
}
```

`full_text` is **truncated to 15 000 chars** before being sent to the LLM, to keep token cost predictable.

### 3.3 `VideoSummarizer`

Constructed lazily (singleton) so that the LLM client is only created on first request, not at app startup. Configuration is via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | (required unless `SUMMARY_MOCK=true`) | API key for the LLM provider |
| `ANTHROPIC_API_KEY` | (optional) | If set, used with `base_url` pointing to Anthropic's OpenAI-compat endpoint |
| `SUMMARY_MODEL` | `gpt-4o-mini` | Model name to send in the request |
| `SUMMARY_BASE_URL` | (optional) | Override OpenAI-compatible `base_url` (for proxies or DeepSeek) |
| `SUMMARY_MOCK` | `false` | If `true`, skip real LLM and emit a canned summary stream (see §3.9) |
| `SUMMARY_TIMEOUT` | `90` | LLM call timeout in seconds (raised from 60 s after review) |

**Timeout is dynamic for long subtitles**: if `subtitle_text` length > 8 000 chars, the effective timeout is `max(SUMMARY_TIMEOUT, len(text) / 200)` seconds (≈ 90 s for a 15 000-char subtitle). This is computed in the SSE handler and enforced via `asyncio.wait_for`.

Three methods:

- `summarize_stream(subtitle_text, language, has_subtitle: bool = True, video_meta: dict | None = None) -> Iterator[str]` — yields summary tokens. When `has_subtitle=False`, the prompt switches to a metadata-only template (see §3.4).
- `generate_mindmap(subtitle_text, language) -> str` — non-streaming, returns markdown (NOT used in MVP but kept for the next iteration to avoid a refactor)
- `chat_stream(subtitle_text, question) -> Iterator[str]` — RAG-style Q&A (NOT used in MVP, same reason)

A separate factory `build_summarizer()` returns either a real `VideoSummarizer` (when `SUMMARY_MOCK` is unset) or a `MockSummarizer` (when `SUMMARY_MOCK=true`). Both implement the same `summarize_stream` interface, so the SSE handler is unchanged.

The `_build_*_prompt` static methods are kept as in the reference.

### 3.4 Prompt template (4-section + structured chapter JSON)

#### 3.4.1 Standard prompt (when subtitles are available)

```
请对以下视频字幕内容进行深度总结分析，使用 {lang} 输出。

视频时长：{duration} 秒。

## 输出结构

### 1. 视频概述
（用 2-3 句话概括视频的主题和核心内容）

### 2. 内容大纲
（按视频内容的逻辑顺序，列出主要章节/段落。
 **章节数量请按视频时长动态调整**：
  - 时长 < 600 秒（< 10 分钟）：2-4 个章节
  - 时长 600-1800 秒（10-30 分钟）：4-6 个章节
  - 时长 1800-3600 秒（30-60 分钟）：6-8 个章节
  - 时长 > 3600 秒（> 60 分钟）：8-12 个章节
 每个章节用一个 `### ` 三级标题，标题文字简洁（≤ 20 字）。
 **不要在标题里嵌入时间戳**——时间戳放到最后的 JSON 块里。）

### 3. 核心知识要点
（提取视频中最重要的知识点、观点或结论，用编号列表形式。最多 8 条。）

### 4. 总结
（用 1-2 句话给出整体评价或一句话总结）

### 5. 章节时间戳（必须输出，结构化 JSON）
**在所有 markdown 之后，另起一行输出一个 JSON 代码块**，格式严格如下：

```json
{"chapters": [{"time": 83, "title": "GPT 的核心机制"}, {"time": 347, "title": "实际应用案例"}]}
```

要求：
- `time` 是整数秒（不是字符串，**不要加引号**）
- 章节顺序按视频中出现的先后顺序
- 章节数量与上面"内容大纲"的章节数量**完全一致**
- 标题文字必须与"内容大纲"中对应章节**完全一致**
- JSON 必须能被 `json.loads` 解析（双引号、无尾逗号、无注释）

正确示例：
```json
{"chapters": [{"time": 0, "title": "开场"}, {"time": 95, "title": "Transformer 原理"}, {"time": 420, "title": "代码实战"}]}
```

错误示例（不要这样写）：
```
- 01:23 GPT 的核心机制
- 05:47 实际应用案例
```

---
视频字幕内容：
{truncated_subtitle}
```

#### 3.4.2 Fallback prompt (when NO subtitles — metadata only)

Used when `has_subtitle=False` (i.e. the extractor returned empty). The user is told via the `subtitle` SSE event that the summary is "基于标题生成".

```
请基于以下视频的元数据生成一个**简短的**总结（不超过 200 字），使用 {lang} 输出。

⚠️ 该视频没有可用的字幕，以下总结**仅基于标题和元数据推测**，精度有限。建议用户观看原视频获取准确信息。

视频标题：{title}
视频平台：{platform}
视频时长：{duration} 秒（{duration_min} 分钟）

## 输出结构

### 1. 视频概述
（基于标题推测视频主题，1-2 句话，**显式声明这是基于标题的猜测**）

### 2. 内容大纲
（**直接说明无法获取字幕内容，请用户观看视频**）

### 3. 核心知识要点
（基于标题推测可能的要点，最多 3 条；不要编造具体细节）

### 4. 总结
（提醒用户此总结基于元数据，强烈建议观看原视频）

### 5. 章节时间戳
输出一个**空数组**：
```json
{"chapters": []}
```
```

#### 3.4.3 Parsing the LLM response

The SSE handler does the following in order:

1. Buffer streaming `summary` tokens into a single `summary_md` string until either:
   - The stream completes naturally (no more tokens), OR
   - A line starting with ```` ```json ```` is detected in the buffered output
2. Split `summary_md` on the first ```` ```json ```` block:
   - Everything before = markdown body (sent to frontend as-is via `summary` event tokens)
   - The code block content = chapter JSON
3. Parse the JSON with `json.loads`. **On parse failure, log a `WARNING` (not `ERROR`) and emit `chapters` with an empty array** — the markdown body is still rendered to the user; only the clickable chapter list is empty. The SSE stream must not abort on chapter-parse failure (a 90-second LLM call should not be wasted because the LLM forgot a trailing comma).
4. Emit one `chapters` SSE event with the parsed `{"chapters": [...]}`.

This means the frontend **never parses timestamps from markdown** — it always gets them from the structured `chapters` event, so the regex fragility the user flagged is eliminated.

`{lang}` is `中文` if `language.startswith("zh")` else the same language as the subtitle.

### 3.5 API: `POST /api/summarize`

**Request** (`application/json`):
```json
{ "url": "https://www.youtube.com/watch?v=...", "language": "zh" }
```

**Response**: `text/event-stream` (SSE), event types:

| Event | Payload | When |
|---|---|---|
| `cache_hit` | JSON `{ "summary": str, "outline": [...], "executive_summary": dict\|null, "subtitle_meta": dict, "cached_at": str }` | Sent **first** if URL+language is in the cache (skips subtitle + LLM). |
| `subtitle` | JSON `SubtitleData` | After subtitle extraction, before summarization. When `has_subtitle=false`, includes `fallback_mode: "metadata"` (see §3.6) |
| `summary` | JSON string (single token) | Per LLM token, streamed (raw JSON — not rendered in frontend, kept for cache compatibility). |
| `outline` | JSON `{ "outline": [OutlineSection, ...] }` | Sent once after Stage 1 LLM completes. Each section has `{title, timestamp, summary[], source_segments[]}`. |
| `summary_md` | string | Overview markdown from Stage 1 (not rendered in UI, kept for cache). |
| `executive_summary` | JSON `{core_topic, key_insights[], author_conclusion, controversies[]}` | Sent once after Stage 2 LLM completes. `null` when quality validation fails. |
| `done` | `[DONE]` literal | Stream end (success). Note: cache hits also emit `done`. |
| `error` | JSON `{ "message": str, "code": str }` | Any failure point |

The `subtitle` event is sent first so the frontend can render the raw subtitles tab immediately, then `summary` tokens stream in. `chapters` arrives once at the end and the frontend turns them into the clickable chapter list. This is the same flow as the reference, plus the structured `chapters` event.

Implementation uses FastAPI's `EventSourceResponse` and `loop.run_in_executor` to call blocking yt-dlp code without freezing the event loop — the same pattern used in the existing `YtdlpService`.

### 3.6 Error handling

| Scenario | HTTP / SSE | User-facing message |
|---|---|---|
| `OPENAI_API_KEY` not set and `SUMMARY_MOCK=false` | SSE `error` (500) | "AI 总结功能未配置：缺少 OPENAI_API_KEY 环境变量（或设置 SUMMARY_MOCK=true 进行调试）" |
| Invalid URL / unsupported platform | SSE `error` (400) | "不支持的视频链接" |
| **No subtitle AND no metadata** (title/duration empty) | SSE `error` (422) | "该视频既无字幕也无元数据，无法生成总结" |
| **No subtitle but has metadata** | SSE `subtitle` with `fallback_mode: "metadata"`, then LLM with fallback prompt (§3.4.2) | (no error; UI shows "基于标题生成的总结" banner) |
| yt-dlp fails to fetch subtitles | SSE `error` (502) | "无法获取字幕：{underlying reason}" |
| LLM call fails | SSE `error` (502) | "AI 总结服务暂时不可用，请稍后重试" |
| LLM call exceeds timeout (90 s default, dynamic for long subtitles) | SSE `error` (504) | "AI 总结超时，请重试或换一个较短的字幕" |
| Private / deleted video | SSE `error` (404) | "视频不可访问" |
| Chapter JSON parse fails (LLM produced invalid JSON) | (no error) | Empty `chapters` array, summary still rendered, debug log |

All errors arrive as SSE `event: error` — the HTTP status stays 200 because the *request* succeeded; the *operation* failed inside the stream.

### 3.7 Configuration

`pyproject.toml` dependency addition (run `uv add openai`):
```toml
"openai>=1.0.0",
```

`httpx>=0.28.1` is already a dependency.

`.env.example`:
```bash
# AI Summary — set OPENAI_API_KEY (or ANTHROPIC_API_KEY) for live mode.
# When SUMMARY_MOCK=true, OPENAI_API_KEY is not required (see §3.9).
OPENAI_API_KEY=sk-xxx
SUMMARY_MODEL=gpt-4o-mini                     # Stage 1 (outline)
EXECUTIVE_SUMMARY_MODEL=gpt-4o-mini           # Stage 2 (exec summary); falls back to SUMMARY_MODEL
# SUMMARY_BASE_URL=https://api.deepseek.com   # uncomment to use DeepSeek
SUMMARY_MOCK=false                            # set true for offline dev
SUMMARY_MOCK_DELAY_MS=50                      # per-token yield rate; 0 for instant tests
SUMMARY_TIMEOUT=90                            # seconds (dynamic for long subs)

# Cache (see §3.8)
SUMMARY_CACHE_PATH=./summary_cache.json       # relative to backend/
SUMMARY_CACHE_TTL_DAYS=30
```

### 3.8 Summary cache

Persists successful summary results in a JSON file keyed by `md5(url + "|" + language)[:16]`, with a configurable TTL (default 30 days). Implementation in `backend/services/summary_cache.py`.

Interface:
```python
class SummaryCache:
    def __init__(self, path: Path, ttl_days: int = 30): ...
    def get(self, url: str, language: str) -> Optional[CachedSummary]: ...
    def set(self, url: str, language: str, data: CachedSummary) -> None: ...

@dataclass
class CachedSummary:
    summary_md: str            # full streamed markdown body
    outline: list[dict]        # [{title, timestamp, summary[], source_segments[]}, ...]
    executive_summary: dict | None  # {core_topic, key_insights, author_conclusion, controversies}
    subtitle_meta: dict        # {has_subtitle, language, subtitle_type, ...}
    cached_at: str             # ISO 8601 timestamp
```

`get()` returns `None` for cache miss **or** when the entry is older than `ttl_days` (expired entries are deleted lazily on access). File writes are atomic (write to `.tmp` then `os.replace`).

The cache file (`summary_cache.json`) is **gitignored** and auto-created on first cache write. A periodic cleanup task is not needed — expired entries are dropped on access and at most one stale entry per access is removed.

**Cache flow in the SSE handler**:
1. Compute cache key
2. If hit + not expired: emit `cache_hit` event with the full `CachedSummary`, then emit `done`. Skip subtitle extraction and LLM entirely.
3. If miss: run the normal subtitle → LLM → chapters flow. On success, write to cache before emitting `done`.

**Cache invalidation**: none manual. To force a re-summarize, the user deletes the file (or wait 30 days). This is acceptable for a local tool with the user's own API key.

### 3.9 Mock mode

When `SUMMARY_MOCK=true`:
- `OPENAI_API_KEY` is **not required** (startup proceeds without warning)
- `MockSummarizer.summarize_stream()` yields a canned markdown body one token at a time (≈ 50ms per token, simulated streaming), then yields the same JSON chapter block
- The `chapters` event fires with 3 fake chapters at `0s`, `90s`, `300s`
- Useful for frontend development, Playwright tests, and demos without burning API credits

Mock data lives in `services/summarizer.py` as a module-level constant `MOCK_SUMMARY_BODY` and `MOCK_CHAPTERS`. The token yield rate is configurable via `SUMMARY_MOCK_DELAY_MS` — **default 50 ms per token** (≈ 3 s total to stream the mock body, so the UI's loading spinner is visible long enough to validate), **`0` for tests** (instant, no spinner visible).

Mock mode **bypasses the cache** (no need to cache mock data) and **bypasses the B站 cookie path** (uses a hardcoded mock URL).

### 3.10 Two-stage architecture (Rev 4)

The summary pipeline is split into two independent LLM calls:

**Stage 1 — Outline + Semantic Segmentation:**
1. Subtitle segments are grouped into semantic chapters via TF-IDF cosine similarity (computed in 30-second sliding windows). Boundary detection uses `mean + 0.75 * std` threshold with a 30-second minimum gap.
2. Chapter text is sent to LLM1 (`SUMMARY_MODEL`, default `mimo-v2.5`) to generate titles and bullet-point summaries per chapter.
3. LLM output is merged with segment-derived timestamps — timestamps come from segmentation, NOT from LLM.
4. Output: `outline` SSE event with `[{title, timestamp, summary[], source_segments[]}]`.

**Stage 2 — Executive Summary:**
1. Structured outline is fed to LLM2 (`EXECUTIVE_SUMMARY_MODEL`) to generate a high-level executive summary.
2. Output: `executive_summary` SSE event (see §3.11).

This separation ensures timestamps are always accurate (derived from subtitle timing) while content analysis benefits from LLM understanding.

### 3.11 Executive Summary (Rev 4)

**Purpose:** Provide a video-level overview (core topic, key insights, author conclusion) distinct from the per-chapter outline.

**Schema:**
```json
{
  "core_topic": "string (10-30 chars)",
  "key_insights": ["string (15-50 chars)", "..."],
  "author_conclusion": "string (20-200 chars)",
  "controversies": ["string"]
}
```

**Configuration:**

| Variable | Default | Purpose |
|---|---|---|
| `EXECUTIVE_SUMMARY_MODEL` | falls back to `SUMMARY_MODEL` | Model for Stage 2 (independent from Stage 1) |
| `EXECUTIVE_SUMMARY_TIMEOUT` | `30` | Timeout in seconds |

**Quality validation** (`parse_executive_summary`):
- `core_topic`: ≥ 20 chars, banned template patterns ("本视频介绍" etc.)
- `key_insights`: ≥ 3 items, each ≥ 10 chars after filtering
- `author_conclusion`: non-empty, banned template patterns ("视频围绕" etc.)
- Dedup + length enforcement (50/200/50 chars)

**Retry logic:** Up to 3 attempts. Retry condition is **parse success** (not string non-emptiness) — the model may return partial/truncated JSON that passes a simple truthiness check but fails validation.

**Fallback:** Returns `None` when all attempts fail. Frontend hides the section (quality gate pattern: better no Executive Summary than low-quality content).

**Prompt:** Concise format — chapter text as `[MM:SS] title\n• bullet` with strict JSON-only output instruction. Tested with `mimo-v2-flash` (reliable) vs `mimo-v2.5` (returns empty consistently).

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
- **Chapter rendering** (replaces the old regex-on-markdown approach): the `chapters` SSE event delivers a `Chapter[]` array; render it as a numbered clickable list **above** the markdown body in the summary tab. Each row shows the time (`formatTime(t)`) and the title. Clicking emits `chapter-click`. **No regex parsing of markdown.**
- **Language banner**: if `subtitleData.is_target_language === false`, show a yellow banner above the summary: "字幕为 {language}，已按原文总结（未翻译）".
- **Metadata-fallback banner**: if `subtitleData.fallback_mode === "metadata"`, show a yellow banner: "该视频无字幕，本总结基于标题生成（精度有限）".
- **Cache hit indicator**: if the first SSE event is `cache_hit`, show a small "✓ 来自缓存 ({cached_at})" badge in the panel header.
- **SSE connection lifecycle**:
  - `useSSE` returns an `AbortController`; store it in a `currentAbort` ref
  - On `onMounted`: start streaming, save controller to `currentAbort`
  - On `onBeforeUnmount`: call `currentAbort.value?.abort()` to close the underlying fetch + ReadableStream — prevents the LLM from continuing to bill after the user navigates away
  - If the user clicks the panel close button (or re-opens it), `currentAbort.value?.abort()` first, then start a new stream
- **Quota UI removed**: the reference's daily-quota banner and "升级 VIP" button are dropped — this is a local tool, not a SaaS.

Props / emits:
```ts
defineProps<{ videoUrl: string; videoTitle?: string }>()
defineEmits<{
  'chapter-click': [timeSec: number]  // bubbles to index.vue → VideoPreview.setCurrentTime + play
  'loading-change': [loading: boolean]
}>()
```

The component auto-starts summarization on `onMounted` (same as the reference). It does not block other UI — the loading spinner lives inside the panel.

### 4.4 `useSSE.ts`

```ts
export function useSSE<T = unknown>(url: string, body: unknown, callbacks: {
  [event: string]: (data: T) => void
}): { abort: () => void }
```

Returns an object with an `abort()` function. Internally holds an `AbortController`; the fetch call is passed `controller.signal`. Calling `abort()` cancels the underlying network request so the LLM token stream stops as soon as the upstream connection is closed by the server. Same wire-format parsing as before (`event:` and `data:` lines separated by blank lines).

### 4.5 `VideoPreview.vue` modification

Add a single `defineExpose` block:
```ts
defineExpose({
  play: () => video.value?.play(),  // returns the Promise so caller can await
  pause: () => video.value?.pause(),
  setCurrentTime: (t: number) => { if (video.value) video.value.currentTime = t },
  getCurrentTime: () => video.value?.currentTime ?? 0,
})
```

The existing internal `currentTime` ref stays as-is — it just gets read externally now. No new state, no new behavior, no risk of breaking the existing preview flow.

**Implementation checklist for the implementer** (this was flagged during design review as easy to forget):
- [ ] The `defineExpose` block actually contains `play`, `pause`, `setCurrentTime`, `getCurrentTime` (TypeScript will catch a missing method if the parent's `videoPreviewRef.value?.play()` calls it; without that call, the missing expose would silently no-op)
- [ ] The parent `index.vue` declares `videoPreviewRef` with the right generic: `ref<InstanceType<typeof VideoPreview> | null>(null)` — without the generic, `videoPreviewRef.value.play` is typed as `unknown` and won't compile

### 4.6 `index.vue` integration

- Keep a `ref<InstanceType<typeof VideoPreview> | null>(null)` (`videoPreviewRef`).
- After parse succeeds, render **two** action buttons next to the quality selector:
  - Existing `[下载到本地]` (unchanged)
  - New `[AI 总结]` — toggles `showSummaryPanel` ref
- When `showSummaryPanel` is true, render `<VideoSummary :video-url="..." @chapter-click="onChapterClick" />` in a new section below `VideoPreview`.
- `onChapterClick(t)`:
  ```ts
  function onChapterClick(t: number) {
    videoPreviewRef.value?.setCurrentTime(t)
    // play() returns a Promise; browsers reject with NotAllowedError when
    // autoplay is blocked (e.g. muted=false + no user-gesture context).
    // We deliberately swallow that error: the user can still press play
    // manually, and we don't want a console error from a chapter click.
    videoPreviewRef.value?.play()?.catch((err) => {
      if (err?.name !== 'NotAllowedError') {
        console.warn('VideoPreview.play() failed:', err)
      }
    })
  }
  ```
  Rationale: clicking a chapter is an intent to "watch this part now"; auto-play is the expected behavior (matches YouTube's own chapter UI). The catch is needed because the click is on a UI element above the `<video>`, so the browser may not always consider it a "user gesture" for autoplay purposes.

The summary panel is mounted only after first click (v-if), so the LLM token stream is not requested until the user actually wants it. When the panel is closed, `VideoSummary.vue`'s `onBeforeUnmount` aborts the SSE connection (see §4.3).

### 4.7 Bilibili (B站) subtitle access — limitations

VidSumAI runs in **visitor mode** by default (no B站 login). Visitor-mode limitations:

- **Public CC subtitles**: ✅ available via `dm/view` API (the path used in §3.2). This is what most B站 educational / lecture content uses.
- **AI-generated subtitles (B站自带的语音转文字)**: ✅ available, but lower quality than human CC.
- **Member-only subtitles (大会员 CC)**: ❌ **not accessible** without a logged-in cookie. The same applies to any private / paywalled video.
- **Premium quality (1080P+)**: requires the Firefox cookie extraction already implemented in the existing `YtdlpService` (see CLAUDE.md §"Bilibili (B站)"). The summary module does **not** need the cookies itself — it only needs the subtitles, which are accessible at lower resolutions too.

If a user runs into "no subtitle" on a B站 video that they can normally see subtitles for, the likely cause is a member-only CC. The UI should not say "B站 字幕被墙" — it should fall back to the metadata-based summary (§3.4.2) and show the metadata-fallback banner.

### 4.8 Frontend info architecture redesign (Rev 4)

**Design principle:** "宁可没有 Executive Summary，也不要显示低质量或重复内容"

**Changes:**
- **Removed `summary_md` rendering** — the markdown body from Stage 1 is no longer displayed. It was redundant with the outline and executive summary.
- **Two information layers only:** Executive Summary (video-level) + Outline (chapter-level).
- **Skeleton loading pattern** for Executive Summary: after `outline` arrives, a spinner shows "正在生成视频概述..." until `executive_summary` arrives or `done` fires.
- **Quality gate:** if `executive_summary` is `null` (Stage 2 LLM failed quality validation), the section is hidden entirely — no skeleton, no fallback content.
- **SSE handler state:** `execSummaryLoading` ref tracks Stage 2 lifecycle (`true` on `outline`, `false` on `executive_summary`/`done`/`error`).
- **`summary_md` handler** kept as no-op for cache compatibility: `(_data: string) => {}`.

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
  is_target_language: boolean  // false when target language unavailable
  fallback_mode?: 'metadata'  // present when has_subtitle=false and metadata was used
  segments: SubtitleSegment[]
  full_text: string
}

export interface Chapter {
  time: number   // seconds (integer from LLM)
  title: string  // ≤ 20 chars
}

export interface ChapterList {
  chapters: Chapter[]
}

// Rev 4 additions
export interface OutlineSection {
  title: string
  timestamp: number       // seconds
  summary: string[]       // bullet points
  source_segments: number[]  // segment indices
}

export interface ExecutiveSummary {
  core_topic: string
  key_insights: string[]
  author_conclusion: string
  controversies: string[]
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
    is_target_language: bool = True
    fallback_mode: Optional[str] = None  # "metadata" when has_subtitle=false
    segments: list[SubtitleSegment] = []
    full_text: str = ""

class Chapter(BaseModel):
    time: int    # seconds
    title: str

class SummarizeRequest(BaseModel):
    url: str
    language: str = "zh"
```

---

## 6. Testing Strategy

### 6.1 Backend unit tests

`tests/test_summarizer.py`:

| Test | What it verifies |
|---|---|
| `test_bilibili_url_detection` | `_is_bilibili_url` matches `bilibili.com` and `b23.tv` |
| `test_vtt_parser_simple` | `_parse_vtt` extracts segments from a known VTT string |
| `test_vtt_parser_dedup` | duplicate consecutive lines are removed |
| `test_subtitle_priority_manual_first` | manual subs beat auto subs at same language |
| `test_subtitle_priority_lang_order` | `zh-Hans` beats `en` beats `ja` |
| `test_subtitle_priority_fallback_to_other_lang` | when no target-lang subtitle exists, picks any other language and sets `is_target_language=False` |
| `test_full_text_truncation` | `full_text` is capped at 15 000 chars |
| `test_prompt_contains_chapter_json_instruction` | prompt template includes the JSON code-block instruction with the correct format |
| `test_prompt_dynamic_chapter_count` | prompt includes duration-aware chapter count guidance |
| `test_fallback_prompt_when_no_subtitle` | prompt switches to metadata-only template when `has_subtitle=False` |
| `test_summarizer_requires_api_key` | `VideoSummarizer()` raises if `OPENAI_API_KEY` is unset and `SUMMARY_MOCK` is not `true` |
| `test_summarizer_skips_api_key_in_mock_mode` | `VideoSummarizer()` does NOT raise when `SUMMARY_MOCK=true` |
| `test_parse_chapter_json_valid` | `_parse_chapter_json` extracts the JSON block from a full LLM response |
| `test_parse_chapter_json_invalid` | invalid JSON → returns `{"chapters": []}` and logs warning, no raise |
| `test_chapter_json_split_preserves_markdown` | when JSON is detected mid-stream, the markdown body is sent to the user intact |
| `test_summarize_endpoint_event_order` | using `httpx.AsyncClient` + `EventSource`-like parser against a stubbed service, verify `subtitle` → `summary` (tokens) → `chapters` → `done` order |
| `test_summarize_endpoint_cache_hit_event` | when cache has the URL+language, only `cache_hit` + `done` events are emitted, no subtitle / summary / chapters |
| `test_summarize_endpoint_no_subtitle_metadata_fallback` | subtitle extractor returns empty, video has metadata → subtitle event has `fallback_mode: "metadata"`, LLM still called with fallback prompt |
| `test_summarize_endpoint_no_subtitle_no_metadata` | subtitle extractor returns empty, no metadata → SSE `error` event with friendly message |
| `test_summarize_endpoint_timeout` | mocked LLM hangs → after `SUMMARY_TIMEOUT` seconds, SSE `error` with 504-style message |
| `test_summarize_endpoint_abort_in_progress` | client disconnects mid-stream → server's blocking `summarize_stream` is cancelled within 1 s (via `asyncio.shield` / task cancellation) |

`tests/test_summary_cache.py`:

| Test | What it verifies |
|---|---|
| `test_cache_set_and_get` | round-trip a `CachedSummary` |
| `test_cache_miss_returns_none` | unknown key returns `None` |
| `test_cache_key_is_deterministic` | same URL+language always produce the same key |
| `test_cache_key_differs_by_language` | same URL, different language → different keys |
| `test_cache_expiry` | entry older than TTL returns `None` and is deleted on access |
| `test_cache_atomic_write` | crash mid-write does not leave a corrupt file (uses `.tmp` + `os.replace`) |
| `test_cache_handles_corrupt_file` | invalid JSON in the cache file → treated as empty, no crash |

The LLM call itself is **not** unit-tested against a live API. Tests use either a fake `OpenAI` client that returns canned streaming chunks, or `MockSummarizer` directly.

### 6.2 Backend integration test (manual)

Documented in the implementation plan as a manual smoke test. Two modes:

**Live mode**:
```bash
# Terminal 1
cd backend && OPENAI_API_KEY=sk-xxx uv run python -m uvicorn main:app --port 8000

# Terminal 2
curl -N -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

Expect: `subtitle` event with `has_subtitle: true`, then a stream of `summary` tokens, then a `chapters` event, then `done`. Errors return `error` event with a friendly message.

**Mock mode (no API key required)**:
```bash
# Terminal 1
cd backend && SUMMARY_MOCK=true uv run python -m uvicorn main:app --port 8000

# Terminal 2 (same curl as above)
```

Expect: a fake summary streams in over ≈ 3 seconds, 3 hardcoded chapters (`0s, 90s, 300s`) appear, `done` follows.

**Cache hit verification**:
```bash
# 1st request: fills cache, hits LLM (or mock)
# 2nd request within 30 days: emits cache_hit event first, no LLM call
ls -la backend/summary_cache.json  # should exist after 1st request
```

### 6.3 Frontend tests

No new e2e tests in this iteration (the existing Playwright suite covers `VideoPreview`; adding summary e2e would require a real LLM key in CI). The summary panel is exercised manually as part of acceptance.

### 6.4 Acceptance checklist

- [ ] YouTube video with subtitles → summary streams in, 4 sections visible, chapters rendered as a clickable list (not parsed from markdown)
- [ ] Clicking a chapter jumps the video to within 1 s of the timestamp **and starts playback**
- [ ] B站 video with CC subtitles → same flow works (test with a known B站 URL)
- [ ] YouTube video **with** non-target-language subtitles (e.g. English-only) → yellow "字幕为英文" banner shown, summary still generated in English
- [ ] YouTube video **without** subtitles but with metadata (title + duration) → yellow "基于标题生成" banner, metadata-fallback prompt used, empty chapters list
- [ ] YouTube video **without** subtitles AND no metadata → friendly error, no crash
- [ ] LLM call taking > 90 s → 504-style error message, button re-enabled
- [ ] `OPENAI_API_KEY` unset and `SUMMARY_MOCK=false` → backend startup logs a clear warning, request returns SSE error
- [ ] `SUMMARY_MOCK=true` and no API key → request succeeds, mock summary streams in, 3 fake chapters appear
- [ ] Same URL requested twice within TTL → second request serves from `cache_hit` event, no LLM call
- [ ] Closing the summary panel mid-stream → SSE connection aborted, LLM token billing stops within 1 s
- [ ] Dark theme matches `index.vue` (no light-mode leaks)
- [ ] TypeScript: `videoPreviewRef.value?.setCurrentTime` compiles without `unknown` errors (proves the `defineExpose` is in place)
- [ ] Existing download flow is unchanged (regression check: parse → preview → download still works for all 9 platforms)

---

## 7. Out of Scope (Explicit)

These are intentionally **not** part of this design. They are listed here so future readers know they were considered:

- **Mind map rendering** — `markmap-lib` + `markmap-view` are not in `package.json` and **will not be added in MVP**. The `VideoSummary.vue` UI keeps the `mindmap` tab in markup as a placeholder (renders "下一迭代" text), so adding the dependency + real rendering later is a non-breaking change.
- **AI Q&A** — same reason. The `chat` method on `VideoSummarizer` exists in code (mirroring the reference) but is not exposed via API or UI.
- **Platforms without subtitles** — TikTok, 抖音, Instagram, 微博, X, Facebook, 小红书. Adding these requires ASR (whisper.cpp or cloud) which is a separate spec. **Metadata-fallback summary** (no LLM, just title + duration → LLM with a different prompt) is in scope as a degraded path.
- **User accounts, quota, payment** — this is a local tool; the LLM cost is borne by whoever holds the API key (likely the dev who runs the backend).
- **Comment analysis** — Eightify's differentiator. Could be added later.
- **Vision-based understanding** (BibiGPT's slide/frame analysis) — requires multimodal models and frame extraction, separate spec.

---

## 8. Open Questions

None blocking. All questions resolved during the design review:

- ~~Should `SUMMARY_MODEL` default to `gpt-4o-mini` or `gpt-4o`?~~ → `gpt-4o-mini`; user can override via env.
- ~~Should the summary panel auto-collapse on chapter click?~~ → No, panel stays open.
- ~~Should we cache summaries per URL?~~ → **Yes**, file-based cache with 30-day TTL (§3.8).
- ~~What if the video has no subtitles?~~ → **Metadata-fallback summary** (§3.4.2), with a clear UI banner. If metadata is also empty, return a friendly error.
- ~~LLM call timeout: 60s or 90s?~~ → 90s default, dynamic for long subtitles (15 000 chars / 200 chars-per-sec).
- ~~How does the frontend get chapter timestamps?~~ → Structured `chapters` SSE event with `[{time, title}]` (no regex on markdown).
- ~~Mock LLM for development?~~ → Yes, `SUMMARY_MOCK=true` env var (§3.9).

---

## 9. References

- Competitive research: `.firecrawl/{bibigpt-home,notegpt-bilibili,eightify-home}.md`
- Reference implementation: `github.com/liyupi/free-video-downloader` (cloned to `/tmp/free-video-downloader` for analysis)
- Existing architecture: [`docs/superpowers/specs/2026-04-25-vidsumai-design.md`](2026-04-25-vidsumai-design.md)
- Existing CLAUDE.md: project conventions for backend services, frontend components, tests
