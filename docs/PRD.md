# VidSumAI — Product Requirements

**Version:** 0.1.0 (MVP)
**Last updated:** 2026-06-07
**Audience:** Product managers, contributors, and end users who want to understand *what* VidSumAI does and *why* — not *how* it's built (see [Architecture & Design](superpowers/) for that).

---

## 1. Background

Online video lives on 9+ different platforms, each with its own download restrictions, watermarks, quality ceilings, and authentication requirements. Casual users who want to save a video for offline viewing or research hit the same walls repeatedly:

- **Watermarks** on TikTok / Instagram
- **Quality caps** (480p on B站 without login, no 4K on Facebook)
- **Tool fragmentation** — one tool per platform, each with its own UI
- **"Direct download" buttons hidden** behind three menu layers on YouTube / X
- **DRM / login walls** on premium content

VidSumAI consolidates this into a single URL-in, preview, download-out experience that works across platforms without the user needing to know what's happening under the hood.

## 2. Target Users

| Persona | Need |
|---------|------|
| **Content creator** | Quickly grab a competitor's video (with permission) for inspiration or reference |
| **Language learner** | Save lecture videos, podcasts, talks for offline study |
| **Researcher / archivist** | Bulk-archive videos from a specific creator or topic |
| **Casual user** | Save a funny clip to share later, without a watermark |

## 3. Core Goal

> **One URL → preview → pick quality → download. No watermark. Works on 9 platforms.**

## 4. Scope (MoSCoW)

### Must Have (MVP — shipped in 0.1.0)

- ✅ Paste URL → parse video metadata (title, thumbnail, duration, available formats)
- ✅ 9-platform support: YouTube, Bilibili, Instagram, TikTok, 抖音, 小红书, 微博, X, Facebook
- ✅ Quality selection: 360p, 480p, 720p, 1080p, 1440p, 4K (whatever the platform exposes)
- ✅ Real-time download progress (percent, speed, ETA)
- ✅ In-browser preview before download — user can verify the video is what they want
- ✅ "Open folder" button after download completes (Windows Explorer / macOS Finder)
- ✅ No-watermark output for TikTok, Instagram
- ✅ DASH audio/video sync for platforms that serve split streams (B站, YouTube, Instagram, 小红书)

### Should Have (planned)

- ⏳ Batch download — multiple URLs at once
- ⏳ Task history — see past downloads
- ⏳ Custom download path (currently saves to browser's default download directory)

### Could Have (deferred)

- ⏳ AI summary — generate a text summary of the video content
- ⏳ Subtitle extraction / burn-in
- ⏳ Audio-only download (MP3)

### Won't Have

- ❌ Premium / member-only content (B站大会员, YouTube Premium, etc.) — out of scope, may violate TOS
- ❌ DRM-protected content (Netflix, Disney+)
- ❌ Video format transcoding — we download the source format, no re-encoding
- ❌ Live stream recording
- ❌ Account / login system on the app itself (we read cookies from the user's existing browser)

## 5. User Stories

### Story 1 — Quick share

> As a casual user, I want to save a TikTok to my phone **without a watermark** so I can re-share it without the platform branding.

**Flow**: paste TikTok URL → click 解析 → preview plays → pick 1080p → click 下载到本地 → file lands in `~/Downloads` → click 打开文件夹 to confirm.

### Story 2 — Lecture download

> As a language learner, I want to download a 45-minute B站 lecture at 1080P with **synchronized audio** so I can watch it on the train.

**Flow**: paste `bilibili.com/video/BV...` URL → backend auto-reads Firefox cookies → 1080P option is available → preview with audio sync → download → file plays in any video player.

### Story 3 — Reference archive

> As a content creator, I want to grab a 4K YouTube video for offline editing reference so I can study the cinematography at full resolution.

**Flow**: paste YouTube URL → with GFW proxy running → 4K option appears in dropdown → preview streams via proxy → download completes → file is 4K MP4, ready to import into a video editor.

### Story 4 — 抖音 without API keys

> As a 抖音 user, I want to download a video I posted myself so I can use a clip in a presentation. yt-dlp's extractor has been broken for this platform for 2 years.

**Flow**: paste 抖音 share URL → backend's 自实现 API signs the request with `a_bogus` and parses directly → preview shows → download works.

### Story 5 — Cross-platform preview

> As a researcher, I want to preview 3 different platforms' videos side-by-side so I can compare which one has the best quality source.

**Flow**: paste URL from each platform → preview each one in the same UI → choose the best source → download.

## 6. Feature Details

### 6.1 Link Parsing

- Input: any URL from a supported platform (full URL, short URL, or share link accepted)
- Output: title, thumbnail, duration, platform name, list of available formats
- Latency target: < 3 seconds for cached results, < 10 seconds for cold
- Errors: invalid URL → friendly "不支持的链接" message; private / deleted video → "视频不可访问"

### 6.2 Quality Selection

- Dropdown is **dynamically populated** from the parse response — we don't hardcode resolution keys
- Each format shows: quality (e.g. "1080p"), codec/container, approximate file size
- For DASH platforms, the video format includes the audio URL inline — frontend pairs them with a hidden `<audio>` element

### 6.3 Real-time Progress

- WebSocket connection per download task
- Updates: `status` (pending / downloading / completed / failed), `progress` (0-100%), `speed` (MB/s), `eta` (seconds), `downloaded` (bytes)
- Progress is byte-proportional across multiple files (video + audio) — correctly reports 50% when the video is fully downloaded and audio is half-done

### 6.4 Download Completion

- File streams as `video/mp4` with `Content-Disposition: attachment` so the browser triggers its save dialog
- On success: success message + "打开文件夹" button + "重新下载" button
- "打开文件夹" calls `POST /api/open-folder` which runs `os.startfile()` (Windows) or `open()` (macOS / Linux)

### 6.5 B站 1080P+ Unlock

- B站 public videos in 1080P+ require a login cookie
- VidSumAI auto-extracts `bilibili.com` cookies from the user's Firefox profile and passes them to yt-dlp
- Cookie extraction failure → graceful fallback to visitor mode (max 480p, no login required)
- Chrome / Edge support is not implemented (their cookie DBs are encrypted with a different scheme) — use Firefox for 1080P+

### 6.6 抖音自实现

- yt-dlp's 抖音 extractor has been broken since 2024-04 because it lacks the `a_bogus` signature parameter
- VidSumAI's `services/douyin.py` calls the Web API directly: fetches `ttwid` cookie from `ttwid.bytedance.com`, signs requests with `a_bogus` from `services/abogus.py`, parses the JSON response
- Bypasses the broken extractor entirely

## 7. UI / UX Principles

- **Dark mode only** — deep black background (`#0a0a0f`), red-yellow gradient accent (`#ff6b6b → #feca57`)
- **Minimal** — single page, single input, one CTA at a time
- **Preview before commitment** — the user always sees what they're about to download
- **Honest progress** — real byte-progress, not fake "spinning loader"
- **No dark patterns** — clear "open folder" after success, no upsells

The detailed component breakdown (VideoPreview, DownloadInput, QualitySelector, ProgressTracker, PlatformList) lives in the [design spec](superpowers/specs/2026-04-25-vidsumai-design.md#ui-设计规范).

## 8. Acceptance Criteria

A release is shippable when all of these hold:

### Functional

- [ ] Parse + preview works for all 9 platforms with valid test URLs
- [ ] Download completes for at least 720p on all 9 platforms
- [ ] 4K works on YouTube (with proxy)
- [ ] 1080P works on B站 (with Firefox login)
- [ ] No watermark on TikTok output
- [ ] DASH audio plays in sync with video on B站, YouTube, Instagram, 小红书

### Edge cases

- [ ] Invalid URL → friendly error, no 500
- [ ] Private / deleted video → friendly error
- [ ] Network drop mid-download → graceful "download failed" message
- [ ] Preview URL expires (YouTube signed URL) → re-parse and resume
- [ ] GFW proxy down → clear "proxy required" error, not silent hang

### UI

- [ ] Desktop layout responsive at 1280×720 and 1920×1080
- [ ] Dark theme is consistent (no light mode leaks)
- [ ] All buttons have visible focus states for keyboard navigation
- [ ] Loading spinners appear within 200ms of action

## 9. Technical Constraints

These are *decisions*, not preferences — see [Architecture](superpowers/specs/) for the *why*:

- **yt-dlp** is the canonical downloader. We use the Python API, not the CLI.
- **FastAPI** for the backend because of async support and WebSocket ergonomics.
- **Vue 3 + Nuxt 3** for the frontend to share TypeScript types with the backend Pydantic models.
- **No database** — task state is in-memory (acceptable because the MVP is single-user, desktop).
- **Server-side preview-merge** is the fallback for platforms whose CDNs block browser access (TikTok, 抖音, X).
- **GFW proxy is opt-in** — only routed for the 5 blocked platforms, not for B站/抖音/小红书/微博.

## 10. Out of Scope (Explicit)

These were considered and rejected for the MVP. Each gets a `Won't Have` reason:

| Idea | Why not |
|------|---------|
| Format conversion (MP4 → MKV, etc.) | Adds ffmpeg pipeline complexity; users can re-encode with Handbrake |
| Subtitle extraction | Most platforms don't have stable subtitle APIs; 3rd-party sites are better |
| Login to premium content | Legal grey area; risks DMCA / TOS issues |
| Mobile app | Web works on mobile browsers; no immediate need for native |
| AI summary | Defer to v0.2+; quality depends on speech-to-text accuracy |

## 11. Open Questions

None blocking 0.1.0. For v0.2+:

- Should batch download be a parallel-server task model (heavier) or a queue (lighter)?
- Where to host the AI summary feature — local model, remote API, or both?
- Should we add a download history UI (currently we log to backend stdout only)?

## 12. Related Documents

- [Architecture & Design Specs](superpowers/) — technical design, data flow, edge cases
- [Implementation Plans](superpowers/plans/) — step-by-step feature plans
- [README](../README.md) — quick start and feature overview
- [CONTRIBUTING](../CONTRIBUTING.md) — how to contribute
