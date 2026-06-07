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
