# Changelog

All notable changes to VidSumAI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Buffered progress bar (YouTube-style gray indicator behind the red playback bar)
- B站 service module with cookie-aware 1080P+ unlock
- Server-side preview-stream integration tests
- `docs/PRD.md` user-facing product requirements document

### Changed
- `yt-dlp` impersonation enabled by adding `curl-cffi` dependency (fixes intermittent TikTok failures)

## [0.1.0] - 2026-06-07

### Added
- **9 platforms supported**: YouTube, Bilibili, Instagram, TikTok, 抖音, 小红书, 微博, X (Twitter), Facebook
- **Quality 360p–4K** selection with dynamic dropdown populated from `/api/parse`
- **In-browser preview** before download — pick quality, play the video, then save
- **DASH audio/video sync** — hidden `<audio>` element paired with `<video>` for split streams
- **No-watermark extraction** for TikTok and Instagram
- **抖音自实现 API** — custom bypass for the `a_bogus` extractor that yt-dlp has been missing since 2024-04
- **B站 1080P+ unlock** via Firefox cookies (visitor fallback to 480p)
- **X (Twitter) cookie auto-read** from Chrome / Edge / Firefox
- **GFW proxy auto-detection** — only routes blocked sites through local proxy (7890 / 10809 / 1080)
- **Real-time progress** via WebSocket (status, percent, speed, ETA, bytes downloaded)
- **Range-request proxy** (`/api/proxy/stream`) for Referer-protected CDN content
- **Open folder in Explorer** after download completes
- **Backend health check**, **local thumbnail cache** (Instagram), and **server-side preview-merge** endpoint
- **Playwright e2e tests** for B站, YouTube, and TikTok preview paths

[Unreleased]: https://github.com/SAX-ops/VidSumAI/compare/0.1.0...HEAD
[0.1.0]: https://github.com/SAX-ops/VidSumAI/releases/tag/0.1.0
