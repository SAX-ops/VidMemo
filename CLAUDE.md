# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VidSumAI is a multi-platform video downloader with a dark, minimal UI and red-yellow gradient branding. Supports 9+ platforms: YouTube, Bilibili, Instagram, TikTok, 抖音, 小红书, 微博, X (Twitter), Facebook.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vue 3 + Nuxt.js 3 + TailwindCSS |
| Backend | Python FastAPI |
| Download Engine | yt-dlp (Python API, not CLI) + 抖音自实现 API |
| Communication | REST API + WebSocket |

## Development Commands

### Backend (Python, uses `uv`)

```bash
cd backend
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000    # Start dev server
uv run pytest                                                     # Run all tests
uv run pytest tests/test_ytdlp.py                                 # Run single test file
uv run pytest -k test_parse_url                                   # Run single test by name
```

### Frontend (Nuxt 3)

```bash
cd frontend
npx nuxi dev                                                      # Start dev server (port 3000)
npx nuxi build                                                    # Production build
```

### E2E Tests (Playwright)

```bash
cd frontend
PROXY_AVAILABLE=1 npx playwright test --project=chromium     # Run all e2e tests
npx playwright test video-preview.spec.ts -g "B站"            # Run a single platform
CI=1 npx playwright test                                       # CI mode (retries=0)
```

Pre-requisites:
- Backend running on `localhost:8000` (skips whole file if unreachable)
- Frontend running on `localhost:3000` (started separately)
- `PROXY_AVAILABLE=1` for YouTube / TikTok tests (skips them otherwise)

Tests are integration-only — they hit the real backend, real proxy, and real video CDNs. Failure messages distinguish between "platform rejected" (skip), "infrastructure down" (skip), and "real bug" (fail). See `docs/superpowers/specs/2026-06-07-video-preview-e2e-design.md` for the full design.

## Architecture

### Backend (`backend/`)

- **`main.py`** — FastAPI app entry point, CORS config (allows localhost:3000/3001/3002)
- **`models.py`** — Pydantic models: `VideoInfo`, `FormatInfo` (with `audio_url` for DASH streams), `ParseRequest`, `DownloadTask`, `ProgressUpdate`
- **`routers/download.py`** — API endpoints: `/api/parse`, `/api/start-download`, `/api/download/{task_id}`, `/ws/progress/{task_id}`, `/api/thumbnail/{filename}`, `/api/proxy/image`, `/api/proxy/stream`, `/api/preview-stream`, `/api/preview-merge`, `/api/open-folder`
- **`services/ytdlp.py`** — `YtdlpService` class wrapping yt-dlp Python API. Key methods: `parse_url()` (extract video info, DASH audio URL detection), `start_download()` (begin async download with progress hooks). Helpers: `_get_firefox_cookie_file()` (read Bilibili cookies), `_download_instagram_thumbnail()` (cache Instagram thumbnails), `_try_with_cookie_fallback()`, `_detect_proxy()` (auto-detect GFW proxy from env vars / common ports), `_needs_proxy()` (GFW site check), `_strip_ansi()` (clean progress strings).
- **`services/douyin.py`** — Douyin (抖音) 自实现 API since yt-dlp's extractor is broken since 2024-04 (missing `a_bogus`). Calls `aweme/v1/web/aweme/detail/` directly with custom params, `ttwid` cookie from `ttwid.bytedance.com`.
- **`services/abogus.py`** — `a_bogus` signature generator for Douyin (bypasses anti-scraping).

**Critical pattern**: yt-dlp runs in a background thread via `asyncio.to_thread()` to avoid blocking the event loop. Progress updates flow through `progress_hooks` callback → in-memory task dict → WebSocket push to frontend. Progress is calculated as byte-proportional across multiple files (video + audio) by detecting file switches via `filename` changes (not byte reset, which is unreliable).

**Known issue**: yt-dlp's `finished` hook returns `filename` of intermediate files (e.g., `.f398.mp4`) rather than the final merged `.mp4`. The download endpoint uses the `output_path` template to predict the final path, and only marks `status: completed` after `ydl.download()` returns.

**Instagram thumbnails**: Instagram CDN (fbcdn.net) blocks direct thumbnail access. During parse, `_download_instagram_thumbnail()` calls yt-dlp with `writethumbnail=True, skip_download=True` to fetch the cover image, saves it to `backend/thumbnails/{md5_hash}.jpg`, and the API returns a local path `/api/thumbnail/{filename}` instead of the CDN URL.

**DASH audio URL detection**: For platforms with DASH-separated streams (Instagram, YouTube, B站), `parse_url` extracts the audio-only stream URL and attaches it to each video format's `audio_url` field. Frontend uses a hidden `<audio>` element synced with `<video>` for preview playback.

**Proxy auto-detection**: `_detect_proxy()` reads `HTTP_PROXY`/`HTTPS_PROXY` env vars or scans common proxy ports (7890 Clash, 10809 V2Ray, 1080 SOCKS). `_needs_proxy()` checks if URL is on a GFW-blocked site (YouTube, Twitter/X, Instagram, Facebook, TikTok) — only these use proxy, others (B站, 抖音, 小红书, 微博) connect directly.

**Preview streaming**: TikTok/抖音/X use server-side yt-dlp download + merge via `/api/preview-stream` (CDN URLs blocked from browser/proxy). YouTube uses direct CDN URL with auth tokens.

### Frontend (`frontend/`)

- **`pages/index.vue`** — Main page: orchestrates URL parsing, video preview, download flow, WebSocket connection
- **`components/`** — `DownloadInput.vue` (URL input with dynamic button text "解析视频"/"解析中..." + loading spinner), `VideoPreview.vue` (custom video player with DASH audio sync, dynamic quality selector, download button), `ProgressTracker.vue` (progress bar + status), `PlatformList.vue` (supported platforms display)
- **`composables/useWebSocket.ts`** — WebSocket composable for real-time progress (currently inline in index.vue; composable exists but not fully integrated)
- **`types/index.ts`** — TypeScript interfaces mirroring backend Pydantic models (includes `audio_url` for DASH)

**Data flow**: URL input → `POST /api/parse` → display preview → user selects quality → `POST /api/start-download` → WebSocket receives progress → on completion → `GET /api/download/{task_id}` → browser save dialog via blob URL.

**Thumbnail URL logic** (`VideoPreview.vue` `thumbnailUrl`): if the backend returns a local path starting with `/api/`, prepend the API base and fetch directly. Otherwise (external CDN URL on Bilibili/Instagram/小红书), route through `/api/proxy/image` to bypass Referer hotlink protection. Never wrap a local path in the proxy — Chrome's ORB will block the resulting JSON error response.

**Video player** (`VideoPreview.vue`): custom controls (no native UI) for cross-browser consistency. SVG Material Design icons (play/pause/volume/fullscreen). Progress bar updates at 60fps via `requestAnimationFrame`. Drag-to-seek pauses audio to avoid noise. Fullscreen state tracked via `fullscreenchange` event.

**Platform routing for preview** (`VideoPreview.vue` `startPreview`):
- TikTok/抖音/X: server-side download+merge via `/api/preview-stream` (CDN blocks browser)
- YouTube: direct CDN URL (URLs include auth tokens, browser plays directly)
- Bilibili/Instagram/小红书/微博/Facebook: direct CDN URL via `/api/proxy/stream` (Referer protection)
- DASH streams: hidden `<audio>` element synced with `<video>` (currentTime sync, play/pause sync)

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| POST | `/api/parse` | Extract video info (title, thumbnail, formats with `audio_url` for DASH) |
| POST | `/api/start-download` | Start download task, returns `task_id` |
| GET | `/api/download/{task_id}` | Stream file as `video/mp4` with attachment header |
| WS | `/api/ws/progress/{task_id}` | Real-time progress: `{status, progress, speed, eta, downloaded}` |
| POST | `/api/open-folder` | Open folder in OS file explorer (Windows) |
| GET | `/api/thumbnail/{filename}` | Serve locally cached thumbnails (Instagram, etc.) |
| GET | `/api/proxy/image?url=<encoded_url>` | Proxy image requests (bypasses Referer hotlink protection; allowlist: bilibili.com, hdslb.com, bfmtv.com, fbcdn.net, cdninstagram.com, xhscdn.com, xiaohongshu.com) |
| GET | `/api/proxy/stream?url=<encoded_url>` | Proxy video/audio stream (supports Range requests for seeking; allowlist includes TikTok/Xiaohongshu domains) |
| GET | `/api/preview-stream?url=<>&quality=<>` | Server-side download+merge for platforms that block browser access (TikTok/抖音/X) |
| POST | `/api/preview-merge` | Merge separate video+audio streams (Instagram DASH) |

## Important Notes

- **Python 必须通过 UV 运行**：本项目使用 UV 管理 Python 环境和依赖，不要直接调用 `python`、`pip` 等命令，一律使用 `uv run python ...`、`uv add ...`、`uv pip install ...`
- **Windows 环境**：本项目在 Windows 上开发，避免使用 Linux 专属命令（如 `chmod`、`ln -s`、`/dev/null`）。路径使用 `os.path.join()` 或 Windows 风格
- yt-dlp is used via Python API (`from yt_dlp import YoutubeDL`), NOT subprocess CLI calls
- Quality mapping uses format specs like `bestvideo[height<=1080]+bestaudio/best[height<=1080]`. The frontend renders the dropdown dynamically from the formats list returned by `/api/parse` — no hardcoded quality keys.
- Format selector for parse: `bv*+ba/b` (try separate video+audio, fallback to best progressive). Works for all platforms including Facebook (where `best[height>=144]` fails).
- The `YtdlpService.tasks` dict holds all task state in memory — lost on backend restart
- **Bilibili (B站)** uses `visitor=true` extractor arg + custom headers (User-Agent, Referer, Origin) to bypass HTTP 412. Public content works in visitor mode (up to 480p). For 1080P+, the service auto-reads cookies from the Firefox profile (`%APPDATA%\Mozilla\Firefox\Profiles\*\cookies.sqlite`) and writes them as a Netscape-format temp file passed via `cookiefile`. Cookie failure auto-falls-back to visitor mode. Multi-P (合集) videos return a playlist — fall back to `entries[0]` for thumbnail/formats.
- **Instagram** thumbnails are CDN-blocked; the service downloads them via yt-dlp `writethumbnail=True, skip_download=True` and caches them locally at `backend/thumbnails/{md5(url)}.jpg`. The `/api/thumbnail/{filename}` endpoint serves them.
- **抖音 (Douyin)**: yt-dlp's extractor is broken since 2024-04 (missing `a_bogus` signature). `services/douyin.py` calls the Web API directly with `a_bogus` from `services/abogus.py` + `ttwid` cookie from `ttwid.bytedance.com`. Routed via `is_douyin()` check in `parse_url` and `start_download`.
- **X (Twitter)** requires login cookies. `_get_base_ydl_opts()` enables `cookiesfrombrowser` for Twitter URLs (priority: Chrome → Edge → Firefox). Read from `%LOCALAPPDATA%\<Browser>\User Data\Default\Cookies`.
- **小红书 (Xiaohongshu)**: CDN URLs on `xhscdn.com` require Referer `https://www.xiaohongshu.com/`. Routed through `/api/proxy/stream` and `/api/proxy/image` (added to allowlist).
- **GFW proxy**: `_detect_proxy()` reads `HTTP_PROXY`/`HTTPS_PROXY` env vars or scans common proxy ports (7890 Clash, 10809 V2Ray, 1080 SOCKS). `_needs_proxy()` only enables proxy for YouTube/Twitter/Instagram/Facebook/TikTok.
- **Platform name consistency**: Backend `parse_url` returns Chinese platform names ("B站" not "Bilibili", "抖音" not "Douyin", "微博" not "Weibo"). Frontend platform checks must use the same Chinese names. `lstrip('www.')` was a bug — use `removeprefix('www.')` for prefix removal.
- **ANSI in progress strings**: yt-dlp output contains ANSI color codes that show as garbled text in the UI. Use `_strip_ansi()` to clean them.
- Frontend API base URL configured in `nuxt.config.ts` runtimeConfig: `http://localhost:8000`
- UI uses custom Tailwind colors: `primary-from` (#ff6b6b), `primary-to` (#feca57), `dark-bg` (#0a0a0f)
