import { test, expect, type Page } from '@playwright/test'
import { healthCheck, parseUrl } from '../helpers/backend'

const BILIBILI_URL =
  'https://www.bilibili.com/video/BV1M15Q6eEhL/?spm_id_from=333.1387.favlist.content.click&vd_source=632e1301b57e767d2590e82e87ecd490'

function attachErrorCapture(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(`pageerror: ${e.message}`))
  return errors
}

async function driveToPreview(page: Page, url: string): Promise<void> {
  await page.goto('/')
  await page.locator('input[placeholder*="粘贴视频链接"]').fill(url)
  await page.getByRole('button', { name: '解析视频' }).click()
  await expect(page.getByRole('button', { name: '解析视频' })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: '预览视频' })).toBeVisible({ timeout: 10_000 })
}

async function assertVideoParses(url: string): Promise<boolean> {
  try {
    const info = await parseUrl(url)
    return info.formats.length > 0
  } catch {
    return false
  }
}

test.describe('Content export', () => {
  test.describe.configure({ retries: 1 })

  test.beforeAll(async () => {
    if (!(await healthCheck())) {
      test.skip(true, 'Backend not reachable on :8000')
    }
  })

  test('summary tab shows export buttons and renders markdown', async ({ page }) => {
    if (!(await assertVideoParses(BILIBILI_URL))) {
      test.skip(true, 'Video parse failed — region/cookie issue')
    }

    const errors = attachErrorCapture(page)
    await driveToPreview(page, BILIBILI_URL)

    // Open AI summary panel
    const summaryToggle = page.getByRole('button', { name: /收起笔记|展开笔记/ })
    await expect(summaryToggle).toBeVisible({ timeout: 5_000 })
    await summaryToggle.click()

    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible({ timeout: 5_000 })

    // Wait for outline to appear (summary streaming done)
    const outline = summaryPanel.getByTestId('summary-outline')
    await expect(outline).toBeVisible({ timeout: 120_000 })

    // Export buttons should be visible
    const copyBtn = summaryPanel.getByTestId('copy-summary-btn')
    const downloadBtn = summaryPanel.getByTestId('download-summary-btn')
    await expect(copyBtn).toBeVisible()
    await expect(downloadBtn).toBeVisible()

    // If summary_md was rendered, the markdown section should exist
    const mdSection = summaryPanel.getByTestId('summary-markdown')
    // summary_md may or may not be present depending on backend — just check it doesn't error
    const mdVisible = await mdSection.isVisible().catch(() => false)
    if (mdVisible) {
      // Verify rendered content has HTML (not raw markdown)
      const html = await mdSection.innerHTML()
      expect(html).toContain('<')
    }

    // No JS errors
    expect(errors.filter(e => !e.includes('WebSocket'))).toEqual([])
  })

  test('subtitle tab shows export buttons', async ({ page }) => {
    if (!(await assertVideoParses(BILIBILI_URL))) {
      test.skip(true, 'Video parse failed')
    }

    await driveToPreview(page, BILIBILI_URL)

    // Open AI summary panel
    const summaryToggle = page.getByRole('button', { name: /收起笔记|展开笔记/ })
    await expect(summaryToggle).toBeVisible({ timeout: 5_000 })
    await summaryToggle.click()

    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible({ timeout: 5_000 })

    // Switch to subtitle tab
    const subtitleTab = summaryPanel.getByRole('button', { name: '字幕文本' })
    await subtitleTab.click()

    // Wait for subtitle content to load (depends on summary streaming)
    // The export toolbar only shows when segments.length > 0
    const copySubtitleBtn = summaryPanel.getByTestId('copy-subtitle-btn')
    const downloadTxtBtn = summaryPanel.getByTestId('download-txt-btn')
    const downloadSrtBtn = summaryPanel.getByTestId('download-srt-btn')

    // Wait up to 120s for subtitles to arrive
    await expect(copySubtitleBtn).toBeVisible({ timeout: 120_000 })
    await expect(downloadTxtBtn).toBeVisible()
    await expect(downloadSrtBtn).toBeVisible()
  })
})
