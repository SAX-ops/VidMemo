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

  test.describe('YouTube (flaky: GFW proxy + buffering)', () => {
    test.describe.configure({ retries: 1 })

    test('plays via frontend dual-track through backend proxy', async ({ page }) => {
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
  })
})
