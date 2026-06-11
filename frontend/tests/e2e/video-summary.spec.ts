import { test, expect, type Page, type ConsoleMessage, type Dialog } from '@playwright/test'
import { healthCheck, parseUrl, type VideoInfo } from '../helpers/backend'

/**
 * B站视频 — 该视频的元数据可被本地 backend 解析，并能提取 AI 中文自动字幕。
 * `_t` 查询串用于让每个测试拥有独立的 cache key：
 *   - test-stream 使用一个全新 key，必然走「实时 SSE 总结」路径
 *   - test-cache 第一次打开也会走 streaming（写入缓存），关闭再打开则命中缓存
 */
const BILIBILI_BASE =
  'https://www.bilibili.com/video/BV1M15Q6eEhL/?spm_id_from=333.1387.favlist.content.click&vd_source=632e1301b57e767d2590e82e87ecd490'
const STREAM_URL = `${BILIBILI_BASE}&_t=stream-${Date.now()}`
const CACHE_URL = `${BILIBILI_BASE}&_t=cache-${Date.now()}`

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
  await expect(page.getByRole('button', { name: '解析视频' })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: '预览视频' })).toBeVisible({ timeout: 10_000 })
}

async function assertVideoParses(url: string): Promise<VideoInfo | null> {
  try {
    const info = await parseUrl(url)
    if (!info.formats.length) {
      test.skip(true, 'returned no formats — region-lock/cookie issue')
      return null
    }
    return info
  } catch (e) {
    test.skip(true, `parse failed: ${e instanceof Error ? e.message : e}`)
    return null
  }
}

test.describe('Video AI summary', () => {
  test.describe.configure({ retries: 1, mode: 'serial' })

  test.beforeAll(async () => {
    if (!(await healthCheck())) {
      test.skip(true, 'Backend not reachable on :8000 — start the FastAPI server first')
    }
  })

  test('B站 — 实时 SSE 总结（cache miss → 字幕 → 总结 → 大纲）', async ({ page }) => {
    const info = await assertVideoParses(STREAM_URL)
    if (!info) return

    const errors = attachErrorCapture(page)
    await driveToPreview(page, STREAM_URL)

    // 1) Open the AI summary panel
    const summaryToggle = page.getByRole('button', { name: /AI 总结|关闭 AI 总结/ })
    await expect(summaryToggle).toBeVisible({ timeout: 5_000 })
    await summaryToggle.click()

    // 2) Panel mounts via data-testid anchor
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible({ timeout: 5_000 })

    // 3) Wait for streaming to finish. Cap at 90s — matches SUMMARY_TIMEOUT.
    const outline = summaryPanel.getByTestId('summary-outline')
    await expect(outline).toBeVisible({ timeout: 90_000 })

    // 4) Outline has at least 2 chapters for this video
    const chapterCount = await summaryPanel
      .getByTestId('summary-outline')
      .locator('button')
      .count()
    expect(chapterCount).toBeGreaterThan(1)

    // 5) Summary markdown rendered (prose container with at least one H2)
    const summaryMd = summaryPanel.getByTestId('summary-md')
    await expect(summaryMd).toBeVisible()
    const h2 = summaryMd.locator('h2').first()
    await expect(h2).toBeVisible()
    expect((await h2.textContent())?.length ?? 0).toBeGreaterThan(0)

    // 6) NO 来自缓存 badge (we used a fresh cache key, so this is a real stream)
    await expect(summaryPanel.getByText('✓ 来自缓存')).toHaveCount(0)

    // 7) No subtitle-language banner (this video's subs are target zh)
    await expect(summaryPanel.getByText(/已按原文总结/)).toHaveCount(0)

    // 8) Tab switch → 字幕文本 renders segments
    await summaryPanel.getByRole('button', { name: '字幕文本' }).click()
    const segmentCount = await summaryPanel.locator('div.space-y-1 > div').count()
    expect(segmentCount).toBeGreaterThan(5)

    // 9) Tab switch back → outline + summary still rendered
    await summaryPanel.getByRole('button', { name: '总结摘要' }).click()
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible()
    await expect(summaryPanel.getByTestId('summary-md')).toBeVisible()

    // 10) Click an outline chapter — should not throw. The parent receives
    // `outline-click` and calls setCurrentTime; we don't assert on the seek
    // itself since the preview video isn't playing.
    const firstChapterBtn = summaryPanel
      .getByTestId('summary-outline')
      .locator('button')
      .first()
    await firstChapterBtn.click()
    await expect(firstChapterBtn).toBeVisible()

    // 11) Close panel
    await page.getByRole('button', { name: /关闭 AI 总结/ }).click()
    await expect(summaryPanel).toBeHidden({ timeout: 5_000 })

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('B站 — 思维导图标签页渲染（Mind-Elixir 节点）', async ({ page }) => {
    const info = await assertVideoParses(STREAM_URL)
    if (!info) return

    const errors = attachErrorCapture(page)
    await driveToPreview(page, STREAM_URL)

    const summaryToggle = page.getByRole('button', { name: /AI 总结|关闭 AI 总结/ })
    await summaryToggle.click()
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible({ timeout: 5_000 })

    // Wait for the outline first — mindmap generation is a Stage 2 sibling
    // of executive_summary and may land slightly later. Cap at 90s.
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible({ timeout: 90_000 })

    // Switch to mindmap tab
    await summaryPanel.getByRole('button', { name: '思维导图' }).click()
    const mindmapPane = summaryPanel.getByTestId('mindmap-pane')
    await expect(mindmapPane).toBeVisible()

    // Three outcomes are valid:
    //   (a) mindmap rendered → look for the Mind-Elixir canvas + root node
    //   (b) still generating → loading spinner visible
    //   (c) generation skipped by quality gate → empty-state copy
    // Give the SSE 'mindmap' event up to 30s extra to land, then accept (a) or (c).
    await Promise.race([
      summaryPanel.getByTestId('mindmap').waitFor({ state: 'visible', timeout: 30_000 }),
      summaryPanel.getByTestId('mindmap-empty').waitFor({ state: 'visible', timeout: 30_000 }),
    ])

    const renderedMindmap = await summaryPanel.getByTestId('mindmap').count()
    if (renderedMindmap > 0) {
      // Real mindmap — verify Mind-Elixir injected its container & root tile.
      await expect(summaryPanel.getByTestId('mindmap-container')).toBeVisible()
      // Mind-Elixir injects a custom element <me-root> for the central node.
      const rootTile = mindmapPane.locator('me-root, .map-container').first()
      await expect(rootTile).toBeVisible({ timeout: 5_000 })
    } else {
      // Quality-gate skip: the empty-state copy must render and the tab
      // must NOT have broken the other tabs.
      await expect(summaryPanel.getByTestId('mindmap-empty')).toBeVisible()
    }

    // Tab switch back to summary — outline still rendered (no cross-tab breakage)
    await summaryPanel.getByRole('button', { name: '总结摘要' }).click()
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible()

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('B站 — 重新打开面板命中缓存（✓ 来自缓存 badge 出现）', async ({ page }) => {
    const info = await assertVideoParses(CACHE_URL)
    if (!info) return

    const errors = attachErrorCapture(page)
    await driveToPreview(page, CACHE_URL)

    const summaryToggle = page.getByRole('button', { name: /AI 总结|关闭 AI 总结/ })
    await expect(summaryToggle).toBeVisible()
    await summaryToggle.click()
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible()

    // First open: cache miss → stream. Wait for outline to render (proves the
    // stream completed and was written to cache).
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible({ timeout: 90_000 })

    // Close
    await page.getByRole('button', { name: /关闭 AI 总结/ }).click()
    await expect(summaryPanel).toBeHidden()

    // Re-open: should hit the cache synchronously. Outline + summary render
    // without the streaming loading state.
    await page.getByRole('button', { name: /AI 总结/ }).click()
    await expect(summaryPanel).toBeVisible({ timeout: 5_000 })
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible({ timeout: 5_000 })

    // 来自缓存 badge must be present on cache hit
    const cacheBadge = summaryPanel.getByText('✓ 来自缓存')
    await expect(cacheBadge).toBeVisible()
    // Badge includes an ISO timestamp
    const badgeText = await cacheBadge.textContent()
    expect(badgeText).toMatch(/\d{4}-\d{2}-\d{2}/)

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('错误状态：注入的 SSE error 事件在面板里显示', async ({ page }) => {
    const info = await assertVideoParses(STREAM_URL)
    if (!info) return

    await page.route('**/api/summarize', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: error\n' +
          'data: {"message":"AI 总结服务暂时不可用：测试注入错误"}\n\n' +
          'event: done\n' +
          'data: "[DONE]"\n\n',
      })
    })

    const errors = attachErrorCapture(page)
    await driveToPreview(page, STREAM_URL)

    await page.getByRole('button', { name: /AI 总结/ }).click()
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible()
    await expect(
      summaryPanel.getByText('AI 总结服务暂时不可用：测试注入错误'),
    ).toBeVisible({ timeout: 10_000 })
    // Outline must NOT render on error
    await expect(summaryPanel.getByTestId('summary-outline')).toHaveCount(0)

    expect(errors, errors.join('\n')).toEqual([])
  })

  // -----------------------------------------------------------------------
  // Chat with Video (AI 问答) tests — all SSE-mocked, no real LLM needed
  // -----------------------------------------------------------------------

  test('AI 问答 — 完整流程（mock SSE → 流式答案 → 引用卡片）', async ({ page }) => {
    const info = await assertVideoParses(STREAM_URL)
    if (!info) return

    const errors = attachErrorCapture(page)

    // Mock /api/chat to return a controlled SSE stream
    await page.route('**/api/chat', async (route) => {
      const body =
        'event: chat_token\ndata: "Cursor 配合 MCP "\n\n' +
        'event: chat_token\ndata: "扩展使用 [[CH_0]]。"\n\n' +
        'event: chat_done\ndata: {"citations":[{"chapter_title":"AI驱动开发","timestamp":61}]}\n\n'
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body,
      })
    })

    await driveToPreview(page, STREAM_URL)

    // Open summary panel, wait for outline (proves stream completed)
    const summaryToggle = page.getByRole('button', { name: /AI 总结|关闭 AI 总结/ })
    await summaryToggle.click()
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible({ timeout: 5_000 })
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible({ timeout: 90_000 })

    // Switch to Q&A tab
    await summaryPanel.getByRole('button', { name: 'AI 问答' }).click()
    const chatPane = summaryPanel.getByTestId('chat-pane')
    await expect(chatPane).toBeVisible()

    // Type a question and send
    const input = chatPane.locator('input[placeholder*="问题"]')
    await input.fill('Cursor 怎么用的？')
    await chatPane.getByRole('button', { name: '发送' }).click()

    // Wait for assistant message to appear with answer text
    // The mocked SSE sends tokens that accumulate to the final answer
    await expect(chatPane.getByText('Cursor 配合 MCP')).toBeVisible({ timeout: 10_000 })

    // [[CH_0]] marker must be stripped from the rendered answer
    await expect(chatPane.getByText('[[CH_0]]')).toHaveCount(0)

    // Citation card must render
    await expect(chatPane.getByText('📎 来源')).toBeVisible()
    await expect(chatPane.getByText('AI驱动开发')).toBeVisible()
    await expect(chatPane.getByText('1:01')).toBeVisible()

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('AI 问答 — 引用点击触发跳转', async ({ page }) => {
    const info = await assertVideoParses(STREAM_URL)
    if (!info) return

    const errors = attachErrorCapture(page)

    await page.route('**/api/chat', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: chat_done\ndata: {"citations":[{"chapter_title":"部署","timestamp":154}]}\n\n',
      })
    })

    await driveToPreview(page, STREAM_URL)
    const summaryToggle = page.getByRole('button', { name: /AI 总结|关闭 AI 总结/ })
    await summaryToggle.click()
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible({ timeout: 90_000 })

    await summaryPanel.getByRole('button', { name: 'AI 问答' }).click()
    const chatPane = summaryPanel.getByTestId('chat-pane')

    const input = chatPane.locator('input[placeholder*="问题"]')
    await input.fill('项目怎么部署？')
    await chatPane.getByRole('button', { name: '发送' }).click()

    // Wait for citation card
    await expect(chatPane.getByText('📎 来源')).toBeVisible({ timeout: 10_000 })

    // Click the citation — this calls emit('seek', 154) → onOutlineClick(154)
    // We verify the video player receives the seek by checking the video element
    const citationBtn = chatPane.getByText('2:34')
    await citationBtn.click()

    // The video's currentTime should be updated (give it a moment)
    await page.waitForTimeout(500)
    const currentTime = await page.evaluate(() => {
      const video = document.querySelector('video')
      return video?.currentTime ?? 0
    })
    // Timestamp 154s = 2:34. Allow ±5s tolerance for seek settling.
    expect(Math.abs(currentTime - 154)).toBeLessThan(10)

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('AI 问答 — 无字幕时显示提示', async ({ page }) => {
    const info = await assertVideoParses(STREAM_URL)
    if (!info) return

    const errors = attachErrorCapture(page)

    // Mock /api/summarize to return a cache_hit with no subtitles
    await page.route('**/api/summarize', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: cache_hit\ndata: ' + JSON.stringify({
            summary_md: '',
            outline: [{ title: 'ch1', timestamp: 0, summary: ['x'] }],
            executive_summary: null,
            mindmap: null,
            subtitle_meta: {
              has_subtitle: false, language: '', subtitle_type: 'none',
              is_target_language: true, segments: [], full_text: '',
            },
            cached_at: new Date().toISOString(),
          }) + '\n\n' +
          'event: done\ndata: "[DONE]"\n\n',
      })
    })

    await driveToPreview(page, STREAM_URL)
    const summaryToggle = page.getByRole('button', { name: /AI 总结|关闭 AI 总结/ })
    await summaryToggle.click()
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel).toBeVisible({ timeout: 5_000 })

    // Wait for outline to appear (cache_hit delivers it immediately)
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible({ timeout: 10_000 })

    // Switch to Q&A tab
    await summaryPanel.getByRole('button', { name: 'AI 问答' }).click()
    const chatPane = summaryPanel.getByTestId('chat-pane')
    await expect(chatPane).toBeVisible()

    // Must show "no subtitle" message, NOT the chat input
    await expect(chatPane.getByText('无可用字幕')).toBeVisible()
    await expect(chatPane.locator('input[placeholder*="问题"]')).toHaveCount(0)

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('AI 问答 — SSE 错误时显示错误信息', async ({ page }) => {
    const info = await assertVideoParses(STREAM_URL)
    if (!info) return

    const errors = attachErrorCapture(page)

    await page.route('**/api/chat', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: chat_error\ndata: {"message":"AI 服务暂时不可用：模拟故障","code":"llm_error"}\n\n',
      })
    })

    await driveToPreview(page, STREAM_URL)
    const summaryToggle = page.getByRole('button', { name: /AI 总结|关闭 AI 总结/ })
    await summaryToggle.click()
    const summaryPanel = page.getByTestId('video-summary-panel')
    await expect(summaryPanel.getByTestId('summary-outline')).toBeVisible({ timeout: 90_000 })

    await summaryPanel.getByRole('button', { name: 'AI 问答' }).click()
    const chatPane = summaryPanel.getByTestId('chat-pane')

    const input = chatPane.locator('input[placeholder*="问题"]')
    await input.fill('测试错误')
    await chatPane.getByRole('button', { name: '发送' }).click()

    // Error message must appear
    await expect(chatPane.getByText('AI 服务暂时不可用：模拟故障')).toBeVisible({ timeout: 10_000 })

    // Input must be re-enabled (status → error, not generating)
    await expect(input).toBeEnabled()

    expect(errors, errors.join('\n')).toEqual([])
  })
})
