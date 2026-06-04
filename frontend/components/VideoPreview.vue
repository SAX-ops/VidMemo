<template>
  <div v-if="videoInfo" class="max-w-2xl mx-auto mt-8 bg-dark-card border border-dark-border rounded-2xl overflow-hidden">
    <!-- Video/Thumbnail Area -->
    <div class="relative aspect-video bg-black">
      <!-- Thumbnail (shown when not playing) -->
      <img
        v-if="!isPlaying"
        :src="thumbnailUrl"
        class="w-full h-full object-contain"
        alt="Video thumbnail"
      />

      <!-- Video Player (shown when playing) -->
      <video
        v-if="isPlaying"
        ref="videoPlayer"
        class="w-full h-full object-contain"
        autoplay
        @play="onVideoPlay"
        @pause="onVideoPause"
        @timeupdate="onTimeUpdate"
        @loadedmetadata="onLoadedMetadata"
        @error="onVideoError"
        @click="togglePlay"
      />

      <!-- Hidden audio element for DASH-separated streams -->
      <audio ref="audioPlayer" />

      <!-- Play Button Overlay (before playing) -->
      <div
        v-if="!isPlaying"
        class="absolute inset-0 flex items-center justify-center bg-black/30 cursor-pointer"
        @click="startPreview"
      >
        <div class="w-20 h-20 rounded-full gradient-bg flex items-center justify-center">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z"/></svg>
        </div>
      </div>

      <!-- Custom Controls -->
      <div
        v-if="isPlaying"
        class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-4 pb-2 pt-8 select-none"
      >
        <!-- Progress Bar -->
        <div
          ref="progressBar"
          class="relative w-full h-5 cursor-pointer mb-1 group"
          @click="seekTo"
          @mousedown="onProgressMouseDown"
          @mousemove="updateHoverTime"
          @mouseleave="hoverTime = null"
        >
          <div class="absolute top-1/2 -translate-y-1/2 left-0 right-0 h-1 bg-white/20 rounded-full group-hover:h-1.5 transition-[height]" />
          <div
            class="absolute top-1/2 -translate-y-1/2 left-0 h-1 bg-primary-from rounded-full group-hover:h-1.5 transition-[height]"
            :style="{ width: progressPercent + '%' }"
          />
          <div
            class="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full -ml-1.5 opacity-0 group-hover:opacity-100 transition-opacity shadow"
            :style="{ left: progressPercent + '%' }"
          />
          <div
            v-if="hoverTime !== null"
            class="absolute -top-7 bg-black/90 text-white text-xs px-2 py-1 rounded pointer-events-none whitespace-nowrap"
            :style="{ left: hoverPos + 'px' }"
          >{{ formatTime(hoverTime) }}</div>
        </div>

        <div class="flex items-center gap-3">
          <!-- Play/Pause -->
          <button class="text-white w-8 h-8 flex items-center justify-center hover:scale-110 transition-transform outline-none" @click="togglePlay">
            <svg v-if="isPaused" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>
          </button>

          <!-- Time -->
          <span class="text-white/80 text-xs tabular-nums">
            {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
          </span>

          <div class="flex-1" />

          <!-- Volume -->
          <button class="text-white w-8 h-8 flex items-center justify-center hover:scale-110 transition-transform outline-none" @click="toggleMute">
            <svg v-if="isMuted" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M3.63 3.63a.996.996 0 000 1.41L7.29 8.7 7 9H4c-.55 0-1 .45-1 1v4c0 .55.45 1 1 1h3l3.29 3.29c.63.63 1.71.18 1.71-.71v-4.17l4.18 4.18c-.49.37-1.02.68-1.6.91-.36.15-.58.53-.58.92 0 .72.73 1.18 1.39.91.8-.33 1.55-.77 2.22-1.31l1.34 1.34a.996.996 0 101.41-1.41L5.05 3.63c-.39-.39-1.02-.39-1.42 0zM19 12c0 .82-.15 1.61-.41 2.34l1.53 1.53c.56-1.17.88-2.48.88-3.87 0-3.83-2.4-7.11-5.78-8.4-.59-.23-1.22.23-1.22.86v.19c0 .38.25.71.61.85C17.18 6.54 19 9.06 19 12zm-8.71-6.29l-.17.17L12 7.76V6.41c0-.89-1.08-1.33-1.71-.7zM16.5 12A4.5 4.5 0 0014 7.97v1.79l2.48 2.48c.01-.08.02-.16.02-.24z"/></svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0014 7.97v8.05c1.48-.73 2.5-2.25 2.5-3.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
          </button>

          <!-- Fullscreen / Exit Fullscreen -->
          <button class="text-white w-8 h-8 flex items-center justify-center hover:scale-110 transition-transform outline-none" @click="toggleFullscreen">
            <svg v-if="isFullscreen" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/></svg>
            <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Video Info -->
    <div class="p-6">
      <div class="flex items-center gap-2 text-sm text-gray-400 mb-2">
        <span class="bg-primary-from/20 text-primary-from px-2 py-0.5 rounded">
          {{ videoInfo.platform }}
        </span>
        <span v-if="videoInfo.duration">
          {{ formatDuration(videoInfo.duration) }}
        </span>
      </div>
      <h3 class="text-white text-lg font-semibold mb-4">
        {{ videoInfo.title }}
      </h3>
      <p class="text-gray-500 text-sm">
        已选画质：{{ qualityLabel }}
      </p>

      <!-- Quality Selector -->
      <div class="mt-3">
        <select
          v-model="selectedQuality"
          class="bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-white text-sm w-full"
        >
          <option
            v-for="q in availableQualities"
            :key="q.value"
            :value="q.value"
          >{{ q.label }}</option>
        </select>
      </div>
    </div>

    <!-- Action Buttons -->
    <div class="px-6 pb-6 flex gap-4">
      <button
        class="flex-1 bg-white/10 border border-white/20 rounded-xl py-3 text-white font-semibold hover:bg-white/20 transition-all"
        @click="startPreview"
      >
        {{ isPlaying ? '重新预览' : '预览视频' }}
      </button>
      <button
        class="flex-1 gradient-bg border-none rounded-xl py-3 text-white font-bold transition-all"
        :class="{
          'opacity-50 cursor-not-allowed hover:-translate-y-0 hover:shadow-none': isDownloading,
        }"
        :disabled="isDownloading"
        @click="handleDownload"
      >
        <span v-if="isDownloading">下载中 {{ safeProgress }}%</span>
        <span v-else>下载到本地</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { VideoInfo } from '~/types'

const props = defineProps<{
  videoInfo: VideoInfo
  modelValue: string
  isDownloading: boolean
  downloadProgress: number
}>()

const emit = defineEmits<{
  'update:modelValue': [quality: string]
  download: []
}>()

const config = useRuntimeConfig()
const apiBase = config.public.apiBase

const isPlaying = ref(false)
const isPaused = ref(false)
const isMuted = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const progressPercent = ref(0)
const hoverTime = ref<number | null>(null)
const hoverPos = ref(0)
const isFullscreen = ref(false)
const progressBar = ref<HTMLElement | null>(null)
const videoPlayer = ref<HTMLVideoElement | null>(null)
const audioPlayer = ref<HTMLAudioElement | null>(null)
let ignoreSync = false

const selectedQuality = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

// Some platforms (Bilibili, Instagram) block direct thumbnail access — use proxy.
// Local thumbnails (e.g. /api/thumbnail/xxx.jpg) are already served by the backend.
const thumbnailUrl = computed(() => {
  const thumb = props.videoInfo.thumbnail
  if (!thumb) return ''
  if (thumb.startsWith('/api/')) {
    return `${apiBase}${thumb}`
  }
  const needsProxy = ['B站', 'Instagram', '小红书'].includes(props.videoInfo.platform)
  if (needsProxy && /^https?:\/\//.test(thumb)) {
    return `${apiBase}/api/proxy/image?url=${encodeURIComponent(thumb)}`
  }
  return thumb
})

// 安全进度值，防止 NaN 或 undefined
const safeProgress = computed(() => {
  const p = props.downloadProgress
  if (typeof p !== 'number' || isNaN(p) || p < 0) return 0
  return Math.round(p)
})

const handleDownload = () => {
  console.log('[VideoPreview] handleDownload called, isDownloading:', props.isDownloading)
  if (props.isDownloading) {
    console.log('[VideoPreview] Skipping because isDownloading is true')
    return
  }
  console.log('[VideoPreview] Emitting download event')
  emit('download')
}

const qualityTag = (height: number): string => {
  if (height >= 2160) return '4K 超高清'
  if (height >= 1440) return '2K'
  if (height >= 1080) return '高清'
  if (height >= 720) return '标清'
  if (height >= 480) return '流畅'
  return '低清'
}

const availableQualities = computed(() => {
  const fmts = props.videoInfo.formats
  if (!fmts.length) return []

  // 所有画质从高到低，最高画质标注"原画"
  return fmts.map((f, i) => {
    const height = parseInt(f.quality) || 0
    const tag = i === 0 ? '原画' : qualityTag(height)
    return {
      value: f.quality,
      label: `${f.quality}（${tag}）.${f.ext}`
    }
  })
})

const selectedFormatIndex = computed(() => {
  return props.videoInfo.formats.findIndex(f => f.quality === props.modelValue)
})

const qualityLabel = computed(() => {
  const fmt = props.videoInfo.formats.find(f => f.quality === props.modelValue)
  if (!fmt) return props.modelValue
  const idx = props.videoInfo.formats.indexOf(fmt)
  const height = parseInt(props.modelValue) || 0
  const tag = idx === 0 ? '原画' : qualityTag(height)
  return `${props.modelValue}（${tag}）`
})

function stopAudio() {
  if (audioPlayer.value) {
    audioPlayer.value.pause()
    audioPlayer.value.removeAttribute('src')
    audioPlayer.value.load()
  }
}

function stopCurrentPreview() {
  ignoreSync = true
  stopProgressLoop()
  if (videoPlayer.value) {
    videoPlayer.value.pause()
    videoPlayer.value.removeAttribute('src')
    videoPlayer.value.load()
  }
  stopAudio()
  isPaused.value = false
  currentTime.value = 0
  duration.value = 0
  progressPercent.value = 0
  hoverTime.value = null
  ignoreSync = false
}

// Video event handlers
function onVideoPlay() {
  isPaused.value = false
  startProgressLoop()
  if (ignoreSync || !audioPlayer.value?.src) return
  audioPlayer.value.currentTime = videoPlayer.value!.currentTime
  audioPlayer.value.play().catch(() => {})
}

function onVideoPause() {
  isPaused.value = true
  stopProgressLoop()
  if (ignoreSync || !audioPlayer.value?.src) return
  audioPlayer.value.pause()
}

function onTimeUpdate() {
  // Audio sync for DASH streams (skip during drag)
  if (audioPlayer.value?.src && !ignoreSync && !isDragging) {
    if (Math.abs(audioPlayer.value.currentTime - videoPlayer.value.currentTime) > 0.3) {
      audioPlayer.value.currentTime = videoPlayer.value.currentTime
    }
  }
}

// Smooth 60fps progress bar via rAF
let rafId = 0
function startProgressLoop() {
  const tick = () => {
    if (!videoPlayer.value) return
    if (!isDragging) {
      currentTime.value = videoPlayer.value.currentTime
      if (videoPlayer.value.duration) {
        progressPercent.value = (videoPlayer.value.currentTime / videoPlayer.value.duration) * 100
      }
    }
    rafId = requestAnimationFrame(tick)
  }
  rafId = requestAnimationFrame(tick)
}
function stopProgressLoop() {
  cancelAnimationFrame(rafId)
}

function onLoadedMetadata() {
  if (!videoPlayer.value) return
  duration.value = videoPlayer.value.duration || 0
}

// Custom control functions
function togglePlay() {
  if (!videoPlayer.value) return
  if (videoPlayer.value.paused) {
    videoPlayer.value.play()
    audioPlayer.value?.play().catch(() => {})
  } else {
    videoPlayer.value.pause()
    audioPlayer.value?.pause()
  }
}

function toggleMute() {
  if (!videoPlayer.value) return
  isMuted.value = !isMuted.value
  videoPlayer.value.muted = isMuted.value
  if (audioPlayer.value) audioPlayer.value.muted = isMuted.value
}

function toggleFullscreen() {
  const container = videoPlayer.value?.parentElement
  if (!container) return
  if (document.fullscreenElement) {
    document.exitFullscreen()
  } else {
    container.requestFullscreen()
  }
}

// Listen for fullscreen changes (handles Esc key exit too)
if (typeof document !== 'undefined') {
  document.addEventListener('fullscreenchange', () => {
    isFullscreen.value = !!document.fullscreenElement
  })
}

function seekTo(e: MouseEvent) {
  if (!videoPlayer.value || !progressBar.value) return
  const rect = progressBar.value.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  const dur = videoPlayer.value.duration || 0
  // Update UI immediately for smooth feel
  progressPercent.value = ratio * 100
  currentTime.value = ratio * dur
  // Seek video (async, browser handles the rest)
  videoPlayer.value.currentTime = ratio * dur
}

let isDragging = false
function onProgressMouseDown(e: MouseEvent) {
  isDragging = true
  if (audioPlayer.value) audioPlayer.value.pause()
  seekTo(e)
  const onMove = (ev: MouseEvent) => { if (isDragging) seekTo(ev) }
  const onUp = () => {
    isDragging = false
    if (audioPlayer.value?.src && !videoPlayer.value?.paused) {
      audioPlayer.value.currentTime = videoPlayer.value!.currentTime
      audioPlayer.value.play().catch(() => {})
    }
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

function updateHoverTime(e: MouseEvent) {
  if (!videoPlayer.value || !progressBar.value) return
  const rect = progressBar.value.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  hoverPos.value = Math.max(0, Math.min(e.clientX - rect.left, rect.width))
  hoverTime.value = ratio * videoPlayer.value.duration
}

function formatTime(seconds: number): string {
  if (!seconds || isNaN(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}


function getVideoUrl(url: string): string {
  // Proxy video through backend to set proper Referer headers for CDNs
  // Bilibili / 小红书: require Referer header, must proxy
  const needsProxy = ['B站', '小红书'].includes(props.videoInfo.platform)
  if (needsProxy) {
    return `${apiBase}/api/proxy/stream?url=${encodeURIComponent(url)}`
  }
  return url
}

function getAudioUrl(url: string): string {
  // Bilibili / 小红书 audio CDN also requires Referer — proxy it
  const needsProxy = ['B站', '小红书'].includes(props.videoInfo.platform)
  if (needsProxy) {
    return `${apiBase}/api/proxy/stream?url=${encodeURIComponent(url)}`
  }
  return url
}

function getPreviewStreamUrl(): string {
  // Use backend yt-dlp streaming for platforms that block both direct and proxy access
  return `${apiBase}/api/preview-stream?url=${encodeURIComponent(props.videoInfo.url)}&quality=${encodeURIComponent(selectedQuality.value)}`
}

async function startPreview() {
  stopCurrentPreview()
  isPlaying.value = true

  await nextTick()

  const fmt = props.videoInfo.formats[selectedFormatIndex.value]
  if (!fmt?.url) return

  if (fmt.audio_url) {
    // DASH-separated streams: use hidden <audio> element synced with <video>
    audioPlayer.value!.src = getAudioUrl(fmt.audio_url)
  }

  // Platforms that need server-side download+merge for preview
  if (['TikTok', '抖音', 'X'].includes(props.videoInfo.platform)) {
    videoPlayer.value!.src = getPreviewStreamUrl()
  } else {
    videoPlayer.value!.src = getVideoUrl(fmt.url)
  }

}

// Reset playback state when a new video is parsed
watch(() => props.videoInfo, () => {
  stopCurrentPreview()
  isPlaying.value = false
})

// Restart preview when quality changes during playback
watch(selectedQuality, () => {
  if (isPlaying.value) {
    startPreview()
  }
})

// Cleanup on unmount
onBeforeUnmount(() => {
  stopCurrentPreview()
})

const onVideoError = () => {
  alert('视频预览加载失败，请尝试其他清晰度或重新解析')
  isPlaying.value = false
}

const formatDuration = (seconds: number) => {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}
</script>

