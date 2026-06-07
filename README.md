# VidSumAI

> Multi-platform video downloader with preview, 4K support, and no-watermark extraction.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Vue 3](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org/)
[![Platforms](https://img.shields.io/badge/platforms-9-orange.svg)](#supported-platforms)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

<!-- TODO: Replace with real screenshot -->
![Screenshot](docs/screenshot.png)

**VidSumAI** lets you paste a video URL, preview it in-browser, pick a quality (360p–4K), and download with no watermark. Supports 9 platforms, with platform-specific workarounds for B站 1080P unlock, 抖音 anti-bot bypass, and GFW-friendly proxy routing.

---

## Features

- **9 platforms** — YouTube, Bilibili, Instagram, TikTok, 抖音, 小红书, 微博, X (Twitter), Facebook
- **Quality 360p–4K** — pick from the dropdown populated by `/api/parse`
- **Preview before download** — play the video in-browser first
- **Buffered progress bar** — YouTube-style gray bar shows load state during DASH streaming
- **DASH audio/video sync** — hidden `<audio>` element for split streams
- **B站 1080P unlock** — auto-reads Firefox cookies; falls back to visitor mode (480p)
- **抖音自实现** — bypasses yt-dlp's broken `a_bogus` extractor since 2024-04
- **No-watermark** — automatic for TikTok, Instagram
- **GFW proxy auto-detect** — only routes GFW sites through local proxy
- **Real-time progress** — WebSocket push of speed / ETA / bytes

---

## Supported Platforms

| Platform | Parse | Download | Notes |
|----------|:-----:|:--------:|-------|
| YouTube | ✅ | ✅ | 360p – 4K; direct CDN with auth tokens |
| Bilibili (B站) | ✅ | ✅ | 1080P+ requires Firefox cookies (visitor mode: ≤480p) |
| Instagram | ✅ | ✅ | Thumbnails cached locally; DASH audio sync |
| TikTok | ✅ | ✅ | No watermark; server-side preview stream |
| 抖音 | ✅ | ✅ | Custom API bypass; yt-dlp extractor broken since 2024-04 |
| 小红书 | ✅ | ✅ | CDN proxy bypasses Referer check |
| 微博 | ✅ | ✅ | Direct CDN |
| X (Twitter) | ✅ | ✅ | Reads Chrome/Edge/Firefox cookies automatically |
| Facebook | ✅ | ✅ | share + Reel links supported |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vue 3 + Nuxt.js 3 + TailwindCSS |
| Backend | Python FastAPI + WebSockets |
| Download engine | yt-dlp (Python API) + 自实现 API for 抖音 |
| Browser streaming | `<video>` + `<audio>` for DASH, `/api/proxy/stream` for Referer-protected CDNs |

---

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- ffmpeg (on PATH; required for DASH stream merging)

### Install

```bash
# 1. Clone
git clone https://github.com/SAX-ops/VidSumAI.git
cd VidSumAI

# 2. Frontend deps
cd frontend
npm install
cd ..

# 3. Backend deps (uses uv)
cd backend
uv sync
cd ..
```

### Run

```bash
# Terminal 1 — backend on :8000
cd backend
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend on :3000
cd frontend
npx nuxi dev
```

Open <http://localhost:3000>, paste a video URL, click **解析视频**, preview it, then **下载到本地**.

For YouTube / TikTok / X / Facebook / Instagram, set your GFW proxy before starting the backend:

```bash
# Windows (PowerShell)
$env:HTTP_PROXY = "http://127.0.0.1:7890"
$env:HTTPS_PROXY = "http://127.0.0.1:7890"

# macOS / Linux
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

The backend auto-detects proxy from env vars or common ports (7890 / 10809 / 1080) and only routes GFW-blocked sites through it.

---

## Project Structure

```
VidSumAI/
├── frontend/                # Nuxt 3 + Vue 3 + Tailwind
│   ├── pages/               # Routes (index.vue = main UI)
│   ├── components/          # VideoPreview, DownloadInput, ProgressTracker, ...
│   ├── composables/         # useWebSocket
│   ├── types/               # TS interfaces mirroring backend models
│   └── tests/e2e/           # Playwright integration tests
├── backend/                 # FastAPI
│   ├── routers/             # /api/parse, /api/start-download, ...
│   ├── services/
│   │   ├── ytdlp.py         # yt-dlp Python API wrapper
│   │   ├── douyin.py        # 抖音 自实现 API
│   │   └── abogus.py        # a_bogus signature for 抖音
│   ├── downloads/           # gitignored
│   ├── previews/            # gitignored, 30min auto-clean
│   └── thumbnails/          # gitignored
├── docs/
│   ├── PRD.md               # Product Requirements (user-facing)
│   └── superpowers/         # Design specs and implementation plans
├── .github/                 # Issue / PR templates, code of conduct
├── CLAUDE.md                # Claude Code project guide
└── README.md
```

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/parse` | Extract video info (title, thumbnail, formats, DASH `audio_url`) |
| `POST` | `/api/start-download` | Start async download task, returns `task_id` |
| `GET`  | `/api/download/{task_id}` | Stream the file as `video/mp4` |
| `WS`   | `/api/ws/progress/{task_id}` | Real-time progress (`status`, `progress`, `speed`, `eta`) |
| `GET`  | `/api/preview-stream` | Server-side download+merge for TikTok / 抖音 / X |
| `GET`  | `/api/proxy/stream` | Video/audio proxy with Range support (Referer bypass) |
| `GET`  | `/api/proxy/image` | Image proxy for Referer-protected thumbnails |
| `POST` | `/api/preview-merge` | Merge separate DASH video + audio streams |
| `GET`  | `/api/thumbnail/{filename}` | Locally cached thumbnails (Instagram) |
| `POST` | `/api/open-folder` | Open download folder in OS file explorer |

Full API spec: see [`docs/superpowers/specs/2026-04-25-vidsumai-design.md`](docs/superpowers/specs/2026-04-25-vidsumai-design.md).

---

## Documentation

| Document | Audience |
|----------|----------|
| [`docs/PRD.md`](docs/PRD.md) | Product requirements, scope, non-goals |
| [`docs/superpowers/specs/`](docs/superpowers/) | Design specs (architecture, decisions, edge cases) |
| [`docs/superpowers/plans/`](docs/superpowers/) | Implementation plans (step-by-step) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev setup, testing, PR workflow |
| [`CHANGELOG.md`](CHANGELOG.md) | Release notes |
| [`CLAUDE.md`](CLAUDE.md) | Claude Code-specific development guide |

---

## Contributing

PRs welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup, testing instructions, and the conventional-commit format. For larger changes, open an issue first to discuss the approach.

By participating, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Disclaimer

This project is for educational and personal use only. Do not use it to download content you don't have the rights to, or to violate any platform's Terms of Service or local laws. Downloaded content's copyright belongs to the original authors.

---

## License

[MIT](LICENSE) © 2026 SAX-ops

---

<details>
<summary><strong>中文说明</strong></summary>

VidSumAI 是一款多平台视频下载工具，支持 YouTube、Bilibili、Instagram、TikTok、抖音、小红书、微博、X、Facebook 共 9 个平台。核心特性：

- **多平台无水印** — 粘贴链接、预览、选画质、一键下载
- **4K 高清支持** — 360p – 4K 全画质选择
- **B 站 1080P+ 解锁** — 自动读取 Firefox Cookie（访客模式最高 480p）
- **抖音自实现** — 绕开 yt-dlp 自 2024-04 失效的 a_bogus 提取器
- **DASH 音视频同步** — B 站、YouTube、小红书等分离流的音画同步播放
- **缓冲进度条** — YouTube 风格的灰色加载指示
- **GFW 代理自动检测** — 只对被墙站点启用本地代理

**安装启动**：

```bash
# 克隆与依赖
git clone https://github.com/SAX-ops/VidSumAI.git
cd VidSumAI
cd frontend && npm install && cd ..
cd backend && uv sync && cd ..

# 启动
cd backend && uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000
cd frontend && npx nuxi dev
```

访问 <http://localhost:3000> 即可使用。

**致谢**：

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — 核心下载引擎
- [FastAPI](https://fastapi.tiangolo.com/) — 后端框架
- [Nuxt 3](https://nuxt.com/) + [Vue 3](https://vuejs.org/) — 前端框架
- 所有贡献者和 Issue 反馈者

</details>
