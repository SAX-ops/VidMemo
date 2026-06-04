<template>
  <div class="min-h-screen bg-dark-bg">
    <!-- Header -->
    <header class="border-b border-dark-border py-5 px-10">
      <div class="flex justify-between items-center max-w-7xl mx-auto">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 gradient-bg rounded-xl flex items-center justify-center text-xl transform -rotate-12">
            ▶
          </div>
          <span class="text-2xl font-bold gradient-text">VidSumAI</span>
        </div>
        <nav class="flex gap-8 items-center">
          <a href="#" class="text-gray-500 text-sm hover:text-white transition-colors">功能</a>
          <a href="#" class="text-gray-500 text-sm hover:text-white transition-colors">价格</a>
          <a href="#" class="text-gray-500 text-sm hover:text-white transition-colors">关于</a>
          <div class="bg-primary-from/15 border border-primary-from/30 rounded-full px-4 py-1.5 text-xs text-primary-from">
            已服务 500 万+ 用户
          </div>
        </nav>
      </div>
    </header>

    <!-- Hero Section -->
    <main class="container mx-auto px-4 py-20">
      <h1 class="text-6xl font-extrabold text-center mb-5 leading-tight">
        <span class="gradient-text">无水印高清</span><br>
        视频一键下载
      </h1>
      <p class="text-gray-400 text-xl text-center mb-6">
        支持 YouTube、TikTok、Instagram 等 50+ 平台
      </p>

      <!-- Selling Points -->
      <div class="flex justify-center gap-6 mb-10">
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <span>⚡</span>
          <span>极速解析</span>
        </div>
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <span>🎬</span>
          <span>8K 超高清</span>
        </div>
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <span>🚫</span>
          <span>无水印</span>
        </div>
        <div class="flex items-center gap-2 bg-primary-from/10 border border-primary-from/20 rounded-full px-5 py-2.5 text-sm text-primary-from">
          <span>📦</span>
          <span>多平台支持</span>
        </div>
      </div>

      <!-- Download Input -->
      <DownloadInput @parsed="handleParsed" />

      <!-- Video Preview -->
      <VideoPreview
        v-if="videoInfo"
        :video-info="videoInfo"
        v-model="selectedQuality"
        :is-downloading="isDownloading"
        :download-progress="displayProgress"
        @download="handleDownload"
      />

      <!-- Progress Tracker -->
      <ProgressTracker
        v-if="progress"
        :progress="progress"
        :filename="videoInfo?.title || 'video'"
        :display-progress="displayProgress"
        @re-download="handleDownload"
      />

      <!-- Platform List -->
      <PlatformList />
    </main>

    <!-- Footer -->
    <footer class="text-center py-10 text-gray-600 text-sm border-t border-dark-border">
      <div class="flex justify-center gap-6 mb-4">
        <a href="#" class="hover:text-white transition-colors">关于我们</a>
        <a href="#" class="hover:text-white transition-colors">使用条款</a>
        <a href="#" class="hover:text-white transition-colors">隐私政策</a>
        <a href="#" class="hover:text-white transition-colors">联系我们</a>
      </div>
      <p>© 2024 VidSumAI. All rights reserved.</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import type { VideoInfo, ProgressUpdate } from '~/types'

const config = useRuntimeConfig()
const apiBase = config.public.apiBase

const videoInfo = ref<VideoInfo | null>(null)
const selectedQuality = ref('1080p')
const progress = ref<ProgressUpdate | null>(null)
const taskId = ref<string | null>(null)
const isDownloading = ref(false)
const displayProgress = ref(0)

let ws: WebSocket | null = null

const handleParsed = (info: VideoInfo) => {
  videoInfo.value = info
  progress.value = null
  isDownloading.value = false
  displayProgress.value = 0
  taskId.value = null
  selectedQuality.value = info.formats[0]?.quality || '1080p'

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
      handleDownloadFile()
    } else if (data.status === 'failed') {
      console.log('[WS] Download failed:', data.error)
      ws?.close()
      isDownloading.value = false
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
  } catch (e: any) {
    console.error('[Download] Error:', e)
    alert('保存失败: ' + (e.message || '未知错误'))
  }
}
</script>
