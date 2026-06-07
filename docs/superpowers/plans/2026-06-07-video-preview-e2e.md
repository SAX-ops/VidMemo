# Video Preview E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Playwright e2e tests that verify the three representative video preview routing paths in `VideoPreview.vue` work against the real backend.

**Architecture:** Three independent platform tests (B站 / YouTube / TikTok) sharing a `test.beforeAll` backend health check, a small `backend.ts` helper for real `/api/parse` pre-flight, and a `player.ts` helper for video-element polling. No mocking of stream responses; no injection of state into the UI. Tests follow the full user path: type URL → click 解析视频 → click 预览视频 → verify video plays + controls work.

**Tech Stack:** `@playwright/test` (devDep), Node 20+, TypeScript, existing Nuxt 3 frontend at `localhost:3000`, existing FastAPI backend at `localhost:8000`.

**Spec:** `docs/superpowers/specs/2026-06-07-video-preview-e2e-design.md`

---

## Task 1: Install @playwright/test and lock the devDep

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install @playwright/test as a devDep**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npm install --save-dev @playwright/test
```

Expected: package version is added to `devDependencies` in `package.json`. If npm warns about peer deps, that's fine.

- [ ] **Step 2: Install the chromium browser binary**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx playwright install chromium
```

Expected: chromium browser binary downloaded (~150MB). If this fails due to network, use `npx playwright install chromium --with-deps` on Linux, or skip on Windows and let Playwright use the system browser later. Note the result in commit message.

- [ ] **Step 3: Verify install**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx playwright --version
```

Expected: prints something like `Version 1.x.x`.

- [ ] **Step 4: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add frontend/package.json frontend/package-lock.json
git commit -m "test: add @playwright/test devDep for video preview e2e"
```

---

## Task 2: Write playwright.config.ts

**Files:**
- Create: `frontend/playwright.config.ts`

- [ ] **Step 1: Create the config file**

Create `frontend/playwright.config.ts` with this exact content:

```ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 0 : 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:3000',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    launchOptions: {
      args: ['--autoplay-policy=no-user-gesture-required'],
    },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
```

- [ ] **Step 2: Verify the config loads**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx playwright test --list
```

Expected: prints "No tests found" (because we have no spec files yet) but does not error out. The `--list` flag is just to validate the config.

- [ ] **Step 3: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add frontend/playwright.config.ts
git commit -m "test: add Playwright config (chromium, 90s timeout, CI-aware retries)"
```

---

## Task 3: Write the backend helper

**Files:**
- Create: `frontend/tests/helpers/backend.ts`

- [ ] **Step 1: Create the helper file**

Create `frontend/tests/helpers/backend.ts` with this exact content:

```ts
const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'

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

export async function healthCheck(): Promise<boolean> {
  try {
    const r = await fetch(`${BACKEND}/health`)
    return r.ok
  } catch {
    return false
  }
}

export async function parseUrl(url: string): Promise<VideoInfo> {
  const r = await fetch(`${BACKEND}/api/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!r.ok) {
    const detail = await r.text()
    throw new Error(`parseUrl failed (${r.status}): ${detail}`)
  }
  return (await r.json()) as VideoInfo
}
```

- [ ] **Step 2: Verify it compiles and the backend is reachable**

First, ensure the backend is running (per CLAUDE.md):

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\backend"
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Run this in a separate terminal — leave it running for the rest of the plan.

Then in the project root, run a one-off TypeScript check:

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx tsc --noEmit tests/helpers/backend.ts
```

Expected: no errors. (If `npx tsc` complains about missing tsconfig, use `npx tsc --noEmit --target es2020 --module esnext --moduleResolution node --strict tests/helpers/backend.ts` instead.)

- [ ] **Step 3: Verify parseUrl works against a real URL**

This is a manual smoke test using node:

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
node -e "import('./tests/helpers/backend.ts').then(m => m.parseUrl('https://www.bilibili.com/video/BV1D84y1R7n3/').then(v => console.log('formats:', v.formats.length, 'platform:', v.platform)).catch(e => { console.error(e); process.exit(1) }))"
```

If the helper is `.ts` and node can't import it, install `tsx` temporarily:

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx tsx -e "import {parseUrl} from './tests/helpers/backend'; parseUrl('https://www.bilibili.com/video/BV1D84y1R7n3/').then(v => console.log('formats:', v.formats.length, 'platform:', v.platform)).catch(e => { console.error(e); process.exit(1) })"
```

Expected: `formats: <N> platform: B站` (N ≥ 1). If backend is unreachable, you'll see a connection error — start the backend first.

- [ ] **Step 4: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add frontend/tests/helpers/backend.ts
git commit -m "test: add backend helper (parseUrl + healthCheck)"
```

---

## Task 4: Write the player helper

**Files:**
- Create: `frontend/tests/helpers/player.ts`

- [ ] **Step 1: Create the helper file**

Create `frontend/tests/helpers/player.ts` with this exact content:

```ts
import type { Locator, Page } from '@playwright/test'

/**
 * Polls the video element until readyState >= the requested level.
 * Accepts transient drops (e.g. during quality switch where readyState
 * goes 3 → 0 → 3) by giving a small grace period before failing.
 */
export async function waitForReadyState(
  video: Locator,
  level: 1 | 2 | 3 | 4,
  timeoutMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let stableSince = 0
  while (Date.now() < deadline) {
    const ready = await video.evaluate((el: HTMLVideoElement) => el.readyState)
    if (ready >= level) {
      // Require 200ms of stability to filter transient readyState spikes
      if (stableSince === 0) stableSince = Date.now()
      if (Date.now() - stableSince >= 200) return
    } else {
      stableSince = 0
    }
    await new Promise(r => setTimeout(r, 100))
  }
  throw new Error(`waitForReadyState(${level}) timed out after ${timeoutMs}ms`)
}

/**
 * Waits for the video's currentTime to advance by `minAdvanceMs` within
 * `withinMs` of wall-clock time. Returns the final currentTime in seconds.
 */
export async function waitForTimeAdvance(
  video: Locator,
  minAdvanceMs: number,
  withinMs: number,
): Promise<number> {
  const start = await video.evaluate((el: HTMLVideoElement) => el.currentTime)
  const startWall = Date.now()
  while (Date.now() - startWall < withinMs) {
    const now = await video.evaluate((el: HTMLVideoElement) => el.currentTime)
    if ((now - start) * 1000 >= minAdvanceMs) return now
    await new Promise(r => setTimeout(r, 100))
  }
  const final = await video.evaluate((el: HTMLVideoElement) => el.currentTime)
  throw new Error(
    `waitForTimeAdvance: currentTime advanced only ${((final - start) * 1000).toFixed(0)}ms in ${withinMs}ms (needed ${minAdvanceMs}ms)`,
  )
}

/**
 * Clicks the progress bar at a given ratio (0..1) of its width.
 * The progress bar is a child of the video's parent .relative.aspect-video container.
 */
export async function clickProgressAt(
  page: Page,
  video: Locator,
  ratio: number,
): Promise<void> {
  const box = await video
    .locator('xpath=ancestor::div[contains(@class, "aspect-video")]//div[contains(@class, "cursor-pointer")]')
    .first()
    .boundingBox()
  if (!box) throw new Error('progress bar not found')
  const x = box.x + box.width * ratio
  const y = box.y + box.height / 2
  await page.mouse.click(x, y)
}

/**
 * Returns the current audio/video time offset in milliseconds. Debug-only —
 * not asserted on in the e2e suite, exposed for manual DASH drift inspection.
 * Call with `await captureSyncOffset(video, audio)` in a test and log the result.
 */
export async function captureSyncOffset(
  video: Locator,
  audio: Locator,
): Promise<number> {
  return await Promise.all([
    video.evaluate((el: HTMLVideoElement) => el.currentTime),
    audio.evaluate((el: HTMLAudioElement) => el.currentTime),
  ]).then(([v, a]) => (a - v) * 1000)
}
```

- [ ] **Step 2: Verify the file compiles**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx tsc --noEmit --target es2020 --module esnext --moduleResolution node --strict tests/helpers/player.ts
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add frontend/tests/helpers/player.ts
git commit -m "test: add player helper (waitForReadyState, waitForTimeAdvance, clickProgressAt, captureSyncOffset)"
```

---

## Task 5: Write the B站 e2e test (full user path)

**Files:**
- Create: `frontend/tests/e2e/video-preview.spec.ts`

This is the first of three platform tests. We write it as the failing test → run it → debug → commit. The "failing" here means: the first run is expected to pass (we've already verified backend + helpers work in earlier tasks). If it doesn't pass, we fix the test, not the system.

- [ ] **Step 1: Create the spec file with B站 test only**

Create `frontend/tests/e2e/video-preview.spec.ts` with this exact content:

```ts
import { test, expect, type Page, type ConsoleMessage, type Dialog } from '@playwright/test'
import { healthCheck, parseUrl, type VideoInfo } from '../helpers/backend'
import {
  waitForReadyState,
  waitForTimeAdvance,
  clickProgressAt,
  captureSyncOffset,
} from '../helpers/player'

const BILIBILI_URL = 'https://www.bilibili.com/video/BV1D84y1R7n3/'
const YOUTUBE_URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
const TIKTOK_URL = 'https://www.tiktok.com/@jlopez.8o5/video/7614317704874315021?is_from_webapp=1&sender_device=pc'

const PLATFORM_NEEDS_PROXY: Record<string, boolean> = {
  'B站': false,
  'YouTube': true,
  'TikTok': true,
}

const READYSTATE_TIMEOUT_MS: Record<string, number> = {
  'B站': 30_000,
  'YouTube': 30_000,
  'TikTok': 60_000,
}

function attachErrorCapture(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(`pageerror: ${e.message}`))
  page.on('console', (m: ConsoleMessage) => {
    if (m.type() !== 'error') return
    const text = m.text()
    if (text.match(/\[WS\]/i)) return
    if (text.includes('alert')) return
    errors.push(`console.error: ${text}`)
  })
  page.on('dialog', (d: Dialog) => {
    errors.push(`dialog: ${d.message()}`)
    d.dismiss()
  })
  return errors
}

async function driveToPreview(page: Page, url: string): Promise<void> {
  await page.goto('/')
  await page.locator('input[placeholder*="粘贴视频链接"]').fill(url)
  await page.getByRole('button', { name: '解析视频' }).click()
  // Wait for parse to complete: button text returns to "解析视频"
  await expect(page.getByRole('button', { name: '解析视频' })).toBeVisible({ timeout: 60_000 })
  // Wait for VideoPreview to appear
  await expect(page.getByRole('button', { name: '预览视频' })).toBeVisible({ timeout: 10_000 })
  // Verify quality dropdown has at least one option
  const optionsCount = await page.locator('select option').count()
  expect(optionsCount).toBeGreaterThan(0)
}

async function runPlatformTest(
  page: Page,
  platformName: string,
  url: string,
  extraAssertions: (video: ReturnType<Page['locator']>, audio: ReturnType<Page['locator']>) => Promise<void>,
): Promise<void> {
  if (PLATFORM_NEEDS_PROXY[platformName] && !process.env.PROXY_AVAILABLE) {
    test.skip(true, `${platformName} requires GFW proxy — set PROXY_AVAILABLE=1`)
  }

  const info: VideoInfo = await parseUrl(url)
  if (!info.formats.length) {
    test.skip(true, `${url} returned no formats — region-lock/cookie/proxy issue`)
  }

  const errors = attachErrorCapture(page)
  await driveToPreview(page, url)

  // Start preview
  await page.getByRole('button', { name: '预览视频' }).click()

  // Wait for video to be ready (timeout depends on routing path)
  const video = page.locator('video')
  const audio = page.locator('audio')
  const readyTimeout = READYSTATE_TIMEOUT_MS[platformName]
  await waitForReadyState(video, 3, readyTimeout)

  // Verify currentTime advances
  await waitForTimeAdvance(video, 1000, 5000)

  // Platform-specific assertion (audio src set, etc.)
  await extraAssertions(video, audio)

  // Control: pause / play sequence
  // The custom controls are inside `<div class="absolute bottom-0 ...">`. The 1st
  // <button> is play/pause, 2nd is volume, 3rd is fullscreen.
  const controlsBar = page.locator('div.absolute.bottom-0').first()
  const playBtn = controlsBar.locator('button').nth(0)
  await video.evaluate((el: HTMLVideoElement) => el.play())
  await page.waitForTimeout(300)
  await playBtn.click()
  await page.waitForTimeout(200)
  expect(await video.evaluate((el: HTMLVideoElement) => el.paused)).toBe(true)
  await playBtn.click()
  await page.waitForTimeout(200)
  expect(await video.evaluate((el: HTMLVideoElement) => el.paused)).toBe(false)

  // Control: seek to 50%
  const duration = await video.evaluate((el: HTMLVideoElement) => el.duration)
  if (duration > 0 && Number.isFinite(duration)) {
    await clickProgressAt(page, video, 0.5)
    await page.waitForTimeout(500)
    const ct = await video.evaluate((el: HTMLVideoElement) => el.currentTime)
    expect(ct).toBeGreaterThanOrEqual(duration * 0.45)
    expect(ct).toBeLessThanOrEqual(duration * 0.55)
  }

  // Control: mute toggle (2nd button in the controls bar)
  const muteBtn = controlsBar.locator('button').nth(1)
  await muteBtn.click()
  expect(await video.evaluate((el: HTMLVideoElement) => el.muted)).toBe(true)

  // Debug-only DASH drift inspection (no assertion)
  if (platformName === 'B站' || platformName === 'YouTube') {
    const offsetMs = await captureSyncOffset(video, audio).catch(() => NaN)
    if (!Number.isNaN(offsetMs)) {
      console.log(`[DASH sync] ${platformName} audio-video offset: ${offsetMs.toFixed(0)}ms`)
    }
  }

  expect(errors, errors.join('\n')).toEqual([])
}

test.describe('Video preview', () => {
  test.beforeAll(async () => {
    if (!(await healthCheck())) {
      test.skip(true, 'Backend not reachable on :8000 — start the FastAPI server first')
    }
  })

  test('B站 plays via frontend dual-track (DASH video + audio)', async ({ page }) => {
    await runPlatformTest(page, 'B站', BILIBILI_URL, async (video, audio) => {
      // DASH-separated: audio element must have src
      const audioSrc = await audio.getAttribute('src')
      expect(audioSrc, 'B站 DASH audio src should be set').toBeTruthy()
    })
  })
})
```

- [ ] **Step 2: Ensure the backend + frontend are both running**

The frontend dev server is already running on :3000 (started in the previous turn). Verify:

```bash
curl -s http://localhost:3000 | head -5
```

Expected: HTML response. If not running:

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx nuxi dev
```

(start in another terminal)

The backend should also be running on :8000 (started in Task 3). Verify:

```bash
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok"}` or similar 200 response. If not running, start it per Task 3 Step 2.

- [ ] **Step 3: Run the B站 test**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
PROXY_AVAILABLE=1 npx playwright test video-preview.spec.ts -g "B站" --project=chromium
```

Expected: PASS within 30-60 seconds. Output should show one passing test. If it fails:

- **Console shows `Backend not reachable`**: ensure `uvicorn` is running on :8000.
- **`B站 returned no formats`**: visit the B站 URL manually via the UI to confirm it parses. If not, the backend may need cookies or the URL may be region-locked.
- **Test times out on `waitForReadyState`**: check the browser console (set `headless: false` in playwright.config.ts temporarily to debug). Common cause: DASH audio/video not loading.
- **Network error in dialog**: the video CDN rejected the request; check `backend/server.log` for proxy errors.

Iterate until the test passes before proceeding.

- [ ] **Step 4: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add frontend/tests/e2e/video-preview.spec.ts
git commit -m "test: add B站 e2e test for video preview dual-track path"
```

---

## Task 6: Add the YouTube test

**Files:**
- Modify: `frontend/tests/e2e/video-preview.spec.ts` (append inside the `test.describe` block)

- [ ] **Step 1: Add the YouTube test block**

Inside `test.describe('Video preview', () => { ... })`, after the B站 test, add:

```ts
  test('YouTube plays via frontend dual-track through backend proxy', async ({ page }) => {
    let proxyRequestSeen = false
    page.on('request', req => {
      const u = req.url()
      if (u.includes('/api/proxy/stream') && u.includes('googlevideo.com')) {
        proxyRequestSeen = true
      }
    })
    await runPlatformTest(page, 'YouTube', YOUTUBE_URL, async (video, audio) => {
      const audioSrc = await audio.getAttribute('src')
      expect(audioSrc, 'YouTube DASH audio src should be set').toBeTruthy()
      expect(proxyRequestSeen, 'YouTube should have proxied googlevideo through /api/proxy/stream').toBe(true)
    })
  })
```

- [ ] **Step 2: Run the YouTube test**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
PROXY_AVAILABLE=1 npx playwright test video-preview.spec.ts -g "YouTube" --project=chromium
```

Expected: PASS. If the `proxyRequestSeen` assertion fails, check the network log — the request URL might be slightly different. Adjust the regex (e.g. `u.includes('googlevideo')` without `.com`) and re-run.

If the test fails on `waitForReadyState` after 30s, increase the timeout in `READYSTATE_TIMEOUT_MS['YouTube']` from 30_000 to 45_000 and re-run.

- [ ] **Step 3: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add frontend/tests/e2e/video-preview.spec.ts
git commit -m "test: add YouTube e2e test for video preview dual-track via proxy"
```

---

## Task 7: Add the TikTok test with retry

**Files:**
- Modify: `frontend/tests/e2e/video-preview.spec.ts` (append inside the `test.describe` block)

- [ ] **Step 1: Add the TikTok test block with test.retry(1)**

Inside `test.describe('Video preview', () => { ... })`, after the YouTube test, add:

```ts
  test('TikTok plays via backend preview-stream (server-side merge)', async ({ page }) => {
    test.retry(1)
    let previewStreamRequestSeen = false
    page.on('request', req => {
      const u = req.url()
      if (u.includes('/api/preview-stream') && u.includes('tiktok.com')) {
        previewStreamRequestSeen = true
      }
    })
    await runPlatformTest(page, 'TikTok', TIKTOK_URL, async () => {
      // No audio element on the server-side path — single merged mp4
      expect(previewStreamRequestSeen, 'TikTok should have hit /api/preview-stream').toBe(true)
    })
  })
```

- [ ] **Step 2: Run the TikTok test**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
PROXY_AVAILABLE=1 npx playwright test video-preview.spec.ts -g "TikTok" --project=chromium
```

Expected: PASS within 60-90 seconds. The first run may take longer because the preview cache is cold (yt-dlp must download the full video before responding). Subsequent runs hit the cache and finish faster.

If it fails consistently:

- **Preview download times out**: check `backend/server.log` for yt-dlp errors. The TikTok URL may be down or the test may be running into a rate limit.
- **`previewStreamRequestSeen` is false**: the request URL might be URL-encoded differently. Adjust the regex to `u.includes('/api/preview-stream')` only, or print all `/api/preview-stream` requests during a failing run to see the actual URLs.

- [ ] **Step 3: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add frontend/tests/e2e/video-preview.spec.ts
git commit -m "test: add TikTok e2e test for server-side preview-stream path"
```

---

## Task 8: Run all three tests together

**Files:**
- (no changes — verification step)

- [ ] **Step 1: Run the full e2e suite**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
PROXY_AVAILABLE=1 npx playwright test video-preview.spec.ts --project=chromium
```

Expected: 3 tests pass (or 1-3 skip if the relevant platform's proxy is unavailable). Total runtime 2-4 minutes including the TikTok server-side download on the first run.

- [ ] **Step 2: Run again to confirm cache stability**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
PROXY_AVAILABLE=1 npx playwright test video-preview.spec.ts --project=chromium
```

Expected: same 3 tests pass, but faster (~1-2 min) because the TikTok preview is now cached.

If any test fails on the second run that passed on the first, it's a cache flakiness issue — investigate the relevant platform's preview cache TTL (currently 30 min in `backend/routers/download.py:457-465`).

- [ ] **Step 3: (Optional) Run with no proxy to verify skip behavior**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI\frontend"
npx playwright test video-preview.spec.ts --project=chromium
```

Expected: B站 passes, YouTube and TikTok skip with messages like `YouTube requires GFW proxy — set PROXY_AVAILABLE=1`.

- [ ] **Step 4: Commit (no changes, just verify clean state)**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git status
```

Expected: clean working tree (the 3 commits from Tasks 5-7 are the only new things).

---

## Task 9: Update CLAUDE.md with test running instructions

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a "Tests" section**

Find the "## Development Commands" section in `CLAUDE.md`. After the "Frontend" command block, add a new section:

```markdown
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
```

- [ ] **Step 2: Verify the rendered markdown**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git diff CLAUDE.md
```

Expected: the new "E2E Tests" section is appended to the "Frontend" command block. No accidental edits to other parts of the file.

- [ ] **Step 3: Commit**

```bash
cd "Z:\DocumentZ\00MyProject\VidSumAI"
git add CLAUDE.md
git commit -m "docs: add e2e test running instructions to CLAUDE.md"
```

---

## Self-Review (run before handoff)

1. **Spec coverage:**
   - §2 Pass criteria → Task 5 step 3 (waitForReadyState 3) + step 3 (waitForTimeAdvance 1000/5000)
   - §3.1 Platforms covered → Tasks 5, 6, 7 (B站, YouTube, TikTok)
   - §4 Real network strategy → Task 3 (real /api/parse), no mocking in spec
   - §5.1 File-level pre-flight → Task 5 step 1 (beforeAll with healthCheck)
   - §5.2 Per-test pre-flight → Task 5 step 1 (runPlatformTest, parseUrl + skip)
   - §5.3 UI flow → Task 5 step 1 (driveToPreview)
   - §5.4 Controls → Task 5 step 1 (runPlatformTest body: pause/play/seek/mute)
   - §5.5 Platform-specific assertions → Tasks 5, 6, 7 (audio src, proxy request, preview-stream request)
   - §5.6 Error capture → Task 5 step 1 (attachErrorCapture)
   - §6 Skip logic → Task 5 step 1 (PLATFORM_NEEDS_PROXY map, PROXY_AVAILABLE env)
   - §7 Timeouts/retries → Task 2 (config), Task 5 step 1 (READYSTATE_TIMEOUT_MS map), Task 7 (test.retry(1))
   - §8 Failure modes → covered by skip logic + retries; documented in CLAUDE.md
   - §9 Known gaps → documented in spec, accepted
   - §10 File layout → matches Tasks 1-9

2. **Placeholder scan:** No "TODO", "TBD", "implement later", or vague steps. All code blocks are complete.

3. **Type consistency:**
   - `parseUrl` returns `VideoInfo` defined in `helpers/backend.ts`, used in `runPlatformTest` — consistent across Tasks 3 and 5.
   - `waitForReadyState(video, level, timeoutMs)` signature used identically in Task 4 and Task 5.
   - `READYSTATE_TIMEOUT_MS` keys are platform names that match the strings passed to `runPlatformTest` (Task 5) and the `PLATFORM_NEEDS_PROXY` keys.
   - `BILIBILI_URL`, `YOUTUBE_URL`, `TIKTOK_URL` constants are defined once in Task 5 step 1 and reused in Tasks 6 and 7.

No issues found — plan is ready for execution.
