<template>
  <div class="min-h-screen bg-dark-bg">
    <!-- Header: 固定顶部 + backdrop blur -->
    <header class="fixed top-0 w-full z-50 border-b border-white/5 py-4 px-4 md:px-10 bg-dark-bg/60 backdrop-blur-xl">
      <div class="flex justify-between items-center max-w-7xl mx-auto">
        <div class="flex items-center gap-3">
          <svg viewBox="0 0 56 56" width="36" height="36" class="flex-shrink-0" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="vidGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#2563EB" />
                <stop offset="100%" stop-color="#06B6D4" />
              </linearGradient>
              <linearGradient id="memoGrad" x1="100%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#34D399" stop-opacity="0.8" />
                <stop offset="100%" stop-color="#3B82F6" stop-opacity="0.2" />
              </linearGradient>
              <filter id="logoGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="2" flood-color="#06B6D4" flood-opacity="0.35"/>
              </filter>
            </defs>
            <g filter="url(#logoGlow)">
              <rect x="2" y="2" width="52" height="52" rx="14" fill="none" stroke="#64748B" stroke-width="1.5" stroke-opacity="0.3" />
              <path d="M14,16 L26,28 L14,40 V16 Z" fill="url(#vidGrad)" />
              <path d="M26,28 L38,16 C43,11 50,15 50,22 V34 C50,42 42,46 35,42 L23,35" fill="none" stroke="url(#memoGrad)" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" />
              <circle cx="26" cy="28" r="2.5" fill="#FFFFFF" />
            </g>
          </svg>
          <span class="text-2xl font-bold text-white font-display tracking-wide" style="text-shadow: 0 0 12px rgba(6,182,212,0.25)">VidMemo</span>
        </div>
        <nav class="flex gap-8 items-center">
          <a href="#" class="text-tertiary text-sm hover:text-white transition-colors">功能</a>
          <a href="#" class="text-tertiary text-sm hover:text-white transition-colors">价格</a>
          <a href="#" class="text-tertiary text-sm hover:text-white transition-colors">关于</a>
        </nav>
      </div>
    </header>

    <!-- Hero Section -->
    <main class="container mx-auto px-4 pt-28 pb-20">
      <h1 class="text-5xl md:text-6xl font-extrabold text-center mb-5 leading-tight max-w-3xl mx-auto font-display">
        看不完的视频<br>
        <span class="gradient-text">AI 帮你划重点</span>
      </h1>
      <p class="text-secondary text-xl text-center mb-6">
        粘贴链接，自动生成章节大纲、核心摘要和思维导图
      </p>

      <!-- Selling Points -->
      <div class="flex justify-center flex-wrap gap-3 mb-10">
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M17.599 6.5a3 3 0 0 0 .399-1.375"/><path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/><path d="M3.477 10.896a4 4 0 0 1 .585-.396"/><path d="M19.938 10.5a4 4 0 0 1 .585.396"/><path d="M6 18a4 4 0 0 1-1.967-.516"/><path d="M19.967 17.484A4 4 0 0 1 18 18"/></svg>
          <span>AI 一键总结</span>
        </div>
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>
          <span>智能问答</span>
        </div>
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          <span>边看边记</span>
        </div>
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>多平台下载</span>
        </div>
      </div>

      <!-- Download Input -->
      <DownloadInput @parsed="handleParsed" />

      <!-- Section: 视频 + AI 笔记 并排布局 (60 / 40,lg+ 生效,<lg 自动堆叠) -->
      <div v-if="videoInfo" class="mt-10">
        <!-- Section header + AI 总结 toggle -->
        <div class="flex items-center gap-3 mb-4">
          <span class="text-sm font-semibold text-secondary uppercase tracking-widest">AI 总结</span>
          <div class="flex-1 h-px bg-dark-border"></div>
          <button
            @click="showSummary = !showSummary"
            class="px-3 py-1 rounded-btn text-sm font-medium transition-all duration-200 ease-out"
            :class="showSummary
              ? 'bg-primary-from/20 text-primary-from border border-primary-from/30'
              : 'bg-dark-card text-secondary border border-dark-border hover:border-primary-from/50 hover:text-primary'"
          >
            {{ showSummary ? '收起笔记' : '展开笔记' }}
          </button>
        </div>

        <!-- Grid: 视频 (60%) | 笔记 (40%);笔记关闭时视频占满 100%。
             视频卡高度由 ResizeObserver 动态同步到总结卡。 -->
        <div class="grid grid-cols-1 lg:grid-cols-5 gap-6 items-stretch">
          <div :class="showSummary ? 'lg:col-span-3' : 'lg:col-span-5'">
            <VideoPreview
              ref="videoPreviewRef"
              :video-info="videoInfo"
              v-model="selectedQuality"
              :is-downloading="isDownloading"
              :download-progress="displayProgress"
              @download="handleDownload"
            />
          </div>
          <div v-if="showSummary" class="lg:col-span-2">
            <VideoSummary
              :visible="showSummary"
              :video-url="videoInfo.url"
              :video-title="videoInfo.title"
              :height="videoCardHeight"
              @outline-click="onOutlineClick"
            />
          </div>
        </div>
      </div>

      <!-- Bug-2: mt-8 让下载区域和视频卡片区视觉分离 -->
      <!-- Progress Tracker -->
      <ProgressTracker
        v-if="progress"
        :progress="progress"
        :filename="videoInfo?.title || 'video'"
        :display-progress="displayProgress"
        :download-state="downloadState"
        class="mt-8"
        @re-download="handleDownload"
      />

      <!-- Platform List -->
      <PlatformList />
    </main>

    <!-- Footer -->
    <footer class="text-center py-10 text-tertiary text-sm border-t border-dark-border">
      <div class="flex justify-center gap-6 mb-4">
        <a href="#" class="hover:text-white transition-colors">关于我们</a>
        <a href="#" class="hover:text-white transition-colors">使用条款</a>
        <a href="#" class="hover:text-white transition-colors">隐私政策</a>
        <a href="#" class="hover:text-white transition-colors">联系我们</a>
      </div>
      <p>© 2026 影记 VidMemo. All rights reserved.</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import type { VideoInfo, ProgressUpdate } from '~/types'
import VideoSummary from '~/components/VideoSummary.vue'

const config = useRuntimeConfig()
const apiBase = config.public.apiBase

const videoInfo = ref<VideoInfo | null>(null)
const selectedQuality = ref('1080p')
const progress = ref<ProgressUpdate | null>(null)
const taskId = ref<string | null>(null)
const isDownloading = ref(false)
const displayProgress = ref(0)
// 下载状态机 —— idle → preparing → triggered(终态) / failed
// - idle:      用户未触发下载 / 下载进行中(显示进度条)
// - preparing: WS 已完成后端下载,blob fetch 进行中(蓝色 spinner)
// - triggered: blob fetch 成功,a.click() 已触发浏览器下载(蓝色 ✓)
// - failed:    blob fetch 失败或 WS 报 failed(红色 ✕)
const downloadState = ref<'idle' | 'preparing' | 'triggered' | 'failed'>('idle')
// P2-Layout: AI 总结默认自动展开(解析成功后无需点击)
const showSummary = ref(true)
const videoPreviewRef = ref<InstanceType<typeof import('~/components/VideoPreview.vue').default> | null>(null)

// ResizeObserver: sync video card height to summary card
const videoCardHeight = ref<number | undefined>(undefined)
let resizeObserver: ResizeObserver | null = null

// Watch for VideoPreview to mount, then observe its height
watch(() => videoInfo.value, () => {
  // Disconnect previous observer
  resizeObserver?.disconnect()
  resizeObserver = null

  // Need nextTick so VideoPreview has mounted after videoInfo is set
  nextTick(() => {
    const el = videoPreviewRef.value?.$el
    if (el) {
      resizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0]
        if (entry) {
          videoCardHeight.value = entry.contentRect.height
        }
      })
      resizeObserver.observe(el)
    }
  })
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})

function onOutlineClick(t: number) {
  videoPreviewRef.value?.setCurrentTime(t)
  // play() returns a Promise; browsers reject with NotAllowedError when
  // autoplay is blocked. We deliberately swallow that error so a chapter
  // click on certain browsers doesn't surface a console error.
  videoPreviewRef.value?.play()?.catch((err) => {
    if (err?.name !== 'NotAllowedError') {
      console.warn('VideoPreview.play() failed:', err)
    }
  })
}

let ws: WebSocket | null = null

const handleParsed = (info: VideoInfo) => {
  videoInfo.value = info
  progress.value = null
  isDownloading.value = false
  displayProgress.value = 0
  taskId.value = null
  selectedQuality.value = info.formats[0]?.quality || '1080p'
  // P2-Layout: 解析后强制展开 AI 总结(即使之前用户收起了)
  showSummary.value = true

  // 关闭之前的 WebSocket
  if (ws) {
    ws.close()
    ws = null
  }
}

const handleDownload = async () => {
  console.log('[DEBUG] handleDownload called')
  console.log('[DEBUG] videoInfo:', !!videoInfo.value)
  console.log('[DEBUG] selectedQuality:', selectedQuality.value)
  console.log('[DEBUG] isDownloading before:', isDownloading.value)

  if (!videoInfo.value) {
    console.log('[DEBUG] videoInfo is null, returning')
    return
  }

  // 重置状态
  progress.value = null
  displayProgress.value = 0
  downloadState.value = 'idle'

  const selectedFormat = videoInfo.value.formats.find(f => f.quality === selectedQuality.value)

  console.log('[DEBUG] selectedFormat:', selectedFormat ? 'found' : 'NOT FOUND')
  console.log('[DEBUG] available formats:', videoInfo.value.formats.map(f => f.quality))

  if (!selectedFormat) {
    alert('未找到对应的清晰度格式，当前选择：' + selectedQuality.value)
    return
  }

  try {
    // 使用原始视频 URL，而不是 direct playback URL
    console.log('[DEBUG] Calling API with url:', videoInfo.value.url)
    const response = await $fetch<{ task_id: string }>(`${apiBase}/api/start-download`, {
      method: 'POST',
      body: {
        url: videoInfo.value.url,
        quality: selectedQuality.value
      }
    })

    console.log('[DEBUG] API response:', response)
    taskId.value = response.task_id
    isDownloading.value = true
    console.log('[DEBUG] isDownloading after set:', isDownloading.value)
    connectWebSocket(response.task_id)
  } catch (e: any) {
    console.error('[DEBUG] API error:', e)
    alert('下载失败: ' + (e.data?.detail || e.message || '未知错误'))
    isDownloading.value = false
  }
}

const connectWebSocket = (id: string) => {
  // 关闭旧连接
  if (ws) {
    console.log('[WS] Closing previous connection')
    ws.close()
    ws = null
  }

  const wsUrl = apiBase.replace('http', 'ws') + `/api/ws/progress/${id}`
  console.log('[WS] Connecting to:', wsUrl)

  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    console.log('[WS] Connected')
  }

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    progress.value = data

    // 进度只取最大值，保证单调递增
    if (data.progress !== undefined && data.progress > displayProgress.value) {
      displayProgress.value = data.progress
    }

    if (data.status === 'completed') {
      console.log('[WS] Download completed, task_id:', taskId.value)
      ws?.close()
      isDownloading.value = false
      // Bug-1: WS 只表示后端完成,不表示浏览器已保存 → 先进 'preparing'
      downloadState.value = 'preparing'
      handleDownloadFile()
    } else if (data.status === 'failed') {
      console.log('[WS] Download failed:', data.error)
      ws?.close()
      isDownloading.value = false
      downloadState.value = 'failed'
    }
  }

  ws.onerror = (error) => {
    console.error('[WS] Error:', error)
  }

  ws.onclose = (event) => {
    console.log('[WS] Closed, code:', event.code, 'reason:', event.reason)
  }
}

const handleDownloadFile = async () => {
  if (!taskId.value || !videoInfo.value) {
    console.log('[Download] Missing taskId or videoInfo')
    return
  }

  try {
    const filename = `${videoInfo.value.title || 'video'}.mp4`
    console.log('[Download] Fetching:', `${apiBase}/api/download/${taskId.value}`)
    const response = await fetch(`${apiBase}/api/download/${taskId.value}`)
    console.log('[Download] Response status:', response.status, 'ok:', response.ok)

    if (!response.ok) {
      throw new Error('Download failed')
    }

    const blob = await response.blob()
    console.log('[Download] Blob size:', blob.size)

    // Use blob URL download — shows in browser download history
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    console.log('[Download] Success! File triggered download.')

    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    // a.click() 已触发浏览器下载,但前端无法检测浏览器是否真正完成保存
    // → 标记为 'triggered'(终态),用户自行管理浏览器下载
    downloadState.value = 'triggered'
  } catch (e: any) {
    console.error('[Download] Error:', e)
    downloadState.value = 'failed'
    // 不再用 alert,改为 ProgressTracker 内联错误 banner
  }
}
</script>
