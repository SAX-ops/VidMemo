# Video Preview E2E Test Design

**Date:** 2026-06-07
**Status:** Design — awaiting user approval
**Scope:** Frontend Playwright e2e tests for `VideoPreview.vue`

## 1. Purpose

Add end-to-end Playwright tests that verify the video preview functionality works for the three representative routing paths in the frontend. The tests sit above the existing component and exercise the real backend (yt-dlp / proxy / preview-stream) so they catch regressions in:

- Platform-specific URL routing inside `VideoPreview.vue` (`dualTrackPlatforms` vs server-side)
- DASH-separated audio/video wiring on the dual-track platforms
- Backend proxy and preview-stream endpoints
- Custom video player controls

They are **not** a substitute for component unit tests or backend unit tests — they are an integration check that the pieces still fit together.

## 2. Pass Criteria

A test passes when **all** of the following hold after `预览视频` is clicked:

1. The `<video>` element has `readyState >= 3` (HAVE_FUTURE_DATA) within the platform-specific timeout (30s for dual-track, 60s for server-side).
2. `video.currentTime` advances by ≥ 1s within 3s of wall-clock playback time.
3. The custom controls behave as expected (see §5).
4. The platform-specific assertion (audio src set / preview-stream request observed) holds.
5. No unfiltered JS console errors or page errors during the run.

## 3. Scope

### 3.1 Platforms covered (3)

| Platform | URL | Routing path | Why chosen |
|---|---|---|---|
| B站 | `https://www.bilibili.com/video/BV1D84y1R7n3/` | Frontend dual-track (DASH video + audio) | Exercises the most complex client-side code path (audio sync, DASH detection) |
| YouTube | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` | Frontend dual-track via proxy | Adds the GFW / proxy wrinkle to the dual-track path |
| TikTok | `https://www.tiktok.com/@jlopez.8o5/video/7614317704874315021?is_from_webapp=1&sender_device=pc` | Backend `/api/preview-stream` (yt-dlp download + merge) | Exercises the server-side merge path that DASH-blocked platforms fall back to |

### 3.2 Out of scope (YAGNI)

- Other 6 platforms (Instagram / 微博 / Facebook / 抖音 / 小红书 / X) — same routing buckets already represented
- Mobile / responsive layouts
- Cross-browser (Firefox, WebKit) — Chromium only
- Pixel-level video content comparison
- DASH audio/video drift measurement (a `captureSyncOffset` helper is provided for manual debugging but not asserted on)
- Fullscreen button behavior (not usable in headless)
- Download flow (`/api/start-download`, WebSocket progress)
- Thumbnail pixel validation (URL is asserted, image data is not)

## 4. Network Strategy

**Real network for everything except test isolation. No mocking of stream responses.**

- `/api/parse` is called twice per test: once in the helper (pre-flight, see §6) and once by the UI when the user clicks 解析视频. Both go to the real backend.
- `/api/proxy/stream` and `/api/preview-stream` go to the real backend, which in turn hits the real CDN / yt-dlp.
- YouTube's short-lived googlevideo.com URLs are acceptable because the parse-to-play gap is 1–2s — well within the signed-URL lifetime.

This is a deliberate trade-off: tests depend on backend + proxy + yt-dlp + platforms all being reachable, but in exchange they catch real bugs (expired URLs, broken CDN routing, wrong Referer) that pure mock-based tests would miss.

## 5. Test Flow

### 5.1 File-level pre-flight (`test.beforeAll`)

```ts
test.beforeAll(async () => {
  // Skip the entire file if the backend is not up. Don't fail.
  try {
    const r = await fetch('http://localhost:8000/health')
    if (!r.ok) throw new Error()
  } catch {
    test.skip(true, 'Backend not reachable on :8000 — start the FastAPI server first')
  }
})
```

Per-platform proxy requirement is checked inside each test, not at file level, because different platforms have different proxy needs (see §6.2).

### 5.2 Per-test pre-flight (in test body, before browser)

```ts
// Verify the URL is parseable in this environment (proxy, cookies, region).
const info = await fetchBackend().parseUrl(URL)
test.skip(!info.formats.length, `${URL} returned no formats — region-lock, cookie, or proxy issue`)
```

This isolates failures: if YouTube proxy is down, only the YouTube test skips; B站 and TikTok still run.

### 5.3 UI flow (full user path)

| Step | Action | Wait / Assertion |
|---|---|---|
| 1 | `page.goto('http://localhost:3000')` | DOM ready |
| 2 | `page.fill('input', URL)` | — |
| 3 | `page.click('button:has-text("解析视频")')` | Button text returns to "解析视频" (loading cleared) |
| 4 | Wait for `VideoPreview` to appear | "预览视频" button is visible |
| 5 | Verify quality dropdown populated | `<select>` has ≥ 1 `<option>` |
| 6 | Click `预览视频` | — |
| 7 | Wait for video ready | `waitForReadyState(videoLocator, 3, platformTimeout)` |
| 8 | Wait for currentTime advance | `waitForTimeAdvance(videoLocator, 1000, 3000)` |
| 9 | Platform-specific assertion | See §5.5 |
| 10 | Exercise controls | See §5.4 |

### 5.4 Controls verified in every test

| Control | Action | Assertion |
|---|---|---|
| Pause / play | Click play btn → wait 200ms → click again → click once more | `video.paused` sequence `false → true → false` |
| Seek | Click progress bar at 50% x-position | `currentTime ∈ [duration × 0.45, duration × 0.55]` |
| Mute | Click volume button | `video.muted === true` |
| Quality switch | If dropdown has ≥ 2 options, select 2nd `<option>` | New `video.src` is set (listen for `loadstart`); then re-run `waitForReadyState(3, 30_000)` |

### 5.5 Platform-specific assertions

| Platform | Additional assertion |
|---|---|
| B站 | `<audio>` element has `src` attribute set and non-empty |
| YouTube | `<audio>` element has `src` attribute set and non-empty; a request URL containing `googlevideo.com` was observed going through the backend proxy (i.e. a `GET /api/proxy/stream?url=…googlevideo.com…` request was captured by `page.on('request')`) |
| TikTok | A `GET /api/preview-stream?url=<tiktok-url>` request was observed in the network log |

### 5.6 Error capture

```ts
const errors: string[] = []
page.on('pageerror', e => errors.push(`pageerror: ${e.message}`))
page.on('console', m => {
  if (m.type() !== 'error') return
  const text = m.text()
  // Known non-fatal noise we ignore
  if (text.match(/\[WS\]/i)) return                    // WebSocket warnings from index.vue
  if (text.includes('alert')) return                   // User-facing alert() calls
  errors.push(`console.error: ${text}`)
})
page.on('dialog', d => {
  // Component's onVideoError raises an alert(); capture for diagnostics
  errors.push(`dialog: ${d.message()}`)
  d.dismiss()
})
// At end of test:
expect(errors, errors.join('\n')).toEqual([])
```

## 6. Skip Logic

### 6.1 Backend not reachable → skip whole file

In `beforeAll`. Use `test.skip()` not `throw`, so the test report shows "skipped" rather than "failed".

### 6.2 Platform-specific proxy requirement

```ts
const PLATFORM_NEEDS_PROXY: Record<string, boolean> = {
  'B站': false,        // Direct connection works
  'YouTube': true,     // GFW-blocked
  'TikTok': true,      // GFW-blocked
}
const proxyAvailable = !!process.env.PROXY_AVAILABLE
const needsProxy = PLATFORM_NEEDS_PROXY[platformName]
if (needsProxy && !proxyAvailable) {
  test.skip(true, `${platformName} requires GFW proxy — set PROXY_AVAILABLE=1 to run`)
}
```

This is in the test body so it runs *after* the parse pre-flight, giving the most accurate skip reason.

## 7. Timeouts & Retries

```ts
// playwright.config.ts
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 90_000,                    // per-test ceiling; most finish in 20–40s
  expect: { timeout: 10_000 },        // single-assertion ceiling
  retries: process.env.CI ? 0 : 1,    // 1 retry locally, 0 in CI for stricter gating
  use: {
    baseURL: 'http://localhost:3000',
    launchOptions: {
      args: ['--autoplay-policy=no-user-gesture-required'],
    },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
```

Per-test `waitForReadyState` uses platform-specific timeouts (30s for B站/YouTube, 60s for TikTok server-side) — these are *inside* the 90s overall test timeout.

`test.retry(1)` is applied per-test on TikTok only (most flaky platform due to yt-dlp download variability):

```ts
test.describe('TikTok (server-side preview-stream)', () => {
  test('plays a video end-to-end', async ({ page }) => {
    test.retry(1)  // 抖音自实现 API + yt-dlp 偶发失败
    // ...
  })
})
```

## 8. Failure Modes and Mitigations

### 8.1 Network / backend

| Risk | Symptom | Mitigation |
|---|---|---|
| Backend not running | `/api/parse` 500/connection refused | `beforeAll` skips whole file |
| GFW proxy down | YouTube/TikTok formats empty or video hangs | Per-test skip with `PROXY_AVAILABLE` env gate |
| YouTube signed URL expired between parse and play | video `@error` event → `onVideoError` alert | Captured in `dialog` listener; error message hints "check proxy" |
| TikTok yt-dlp download intermittent | 60s timeout hit | `test.retry(1)` on TikTok only |
| Backend preview cache miss first time | First TikTok run is slow | Accepted; cache warms up on 2nd run |

### 8.2 Browser / playback

| Risk | Symptom | Mitigation |
|---|---|---|
| Headless autoplay blocked | `play()` rejects | `--autoplay-policy=no-user-gesture-required` flag |
| `onVideoError` raises alert | Modal blocks subsequent clicks | `page.on('dialog')` dismisses and captures |
| DASH audio slow to load | `audio.readyState` low | Only assert `audio.src` is set, not `audio.readyState` |
| Video first-frame black | currentTime > 0 but visually nothing | Don't validate pixels; time-based assertion only |

### 8.3 Vue component state

| Risk | Symptom | Mitigation |
|---|---|---|
| `watch(videoInfo)` resets `isPlaying` mid-test | Video stops | Tests only trigger one parse per run |
| Quality switch causes readyState to drop to 0 then climb | Polling assertion could see the dip | `waitForReadyState` is a polling function, accepts transient drops |
| `stopCurrentPreview` not finished before new src set | Stale buffered data | Wait for `loadstart` after quality switch before continuing |

### 8.4 CI / environment

| Risk | Mitigation |
|---|---|
| CI has no GFW proxy | Platform-level skip; doesn't fail CI |
| CI backend not up | File-level skip |
| WebSocket console warnings (`[WS]` prefix) | Filtered in §5.6 |
| Backend `print()` debug output | Tests don't read backend logs; isolation is by HTTP boundary |

## 9. Known Test Gaps (Documented, Not Fixed)

- **Thumbnail pixel validation** — only URL is asserted; image content not checked.
- **DASH audio/video drift** — `captureSyncOffset` helper exists in `helpers/player.ts` for manual debugging; no automated assertion.
- **Fullscreen button** — unusable in headless; skipped.
- **Download flow** — separate spec / test suite.
- **Alert UX** — alert presence is detected, but the modal interaction itself isn't e2e-testable.
- **Network failure injection** — no test for "what if YouTube CDN is down mid-playback"; covered by existing backend error handling, not these tests.

## 10. File Layout

```
frontend/
├── playwright.config.ts            # NEW, ~40 lines
├── tests/
│   ├── e2e/
│   │   └── video-preview.spec.ts   # NEW, 3 tests + beforeAll, ~150 lines
│   └── helpers/
│       ├── backend.ts              # NEW, parseUrl() + healthCheck(), ~25 lines
│       └── player.ts               # NEW, ~60 lines
│                                     #   - waitForReadyState(locator, level, timeoutMs)
│                                     #   - waitForTimeAdvance(locator, ms, withinMs)
│                                     #   - clickProgressAt(videoLocator, ratio)
│                                     #   - captureSyncOffset(video, audio)  // debug-only
└── package.json                    # MOD: devDeps += "@playwright/test"
```

**Total: ~280 lines added, 1 new dependency. No backend or component changes.**

## 11. Decisions Log

Decisions confirmed with the user through the brainstorming session:

1. **Pass criteria**: video `readyState >= 3` + `currentTime` advances + controls work + no JS errors. Rejected pixel comparison and DOM-only checks.
2. **Coverage**: 3 platforms representing 3 routing mechanisms (dual-track direct, dual-track via proxy, server-side merge). Rejected single-platform and 9-platform approaches.
3. **Network strategy**: Real `/api/parse` per test, real proxy and preview-stream, no mocking of stream responses.
4. **Test driver**: Full user path (type URL → click parse → click preview) — closest to real user, no injected state.
5. **Skip logic**: File-level on backend unreachable; per-test on proxy unavailable; per-test on parse returning no formats.
6. **Timeouts**: 30s for dual-track `waitForReadyState`, 60s for server-side; 90s overall test ceiling.
7. **Seek tolerance**: `[duration × 0.45, duration × 0.55]`.
8. **Error filtering**: ignore `[WS]...` console messages and `alert(...)` traces.
9. **Retries**: 1 locally, 0 in CI; `test.retry(1)` per-test on TikTok only.
10. **Debug helpers**: `captureSyncOffset` exposed in `player.ts` for manual DASH drift inspection (not asserted).

## 12. Open Questions

None — all design decisions are settled and the implementation plan is ready to be written via the `writing-plans` skill.
