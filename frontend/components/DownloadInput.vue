<template>
  <div class="max-w-2xl mx-auto">
    <!-- Glass 输入框：backdrop-blur + 半透明背景 + focus glow -->
    <div class="relative bg-white/[0.04] backdrop-blur-xl border border-white/[0.08] rounded-[2rem] p-2 shadow-card transition-all duration-300 focus-within:border-primary-from/40 focus-within:shadow-[0_0_24px_rgba(255,107,107,0.15)]">
      <div class="flex items-center gap-2">
        <div class="flex-grow flex items-center pl-5">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-tertiary mr-3 flex-shrink-0"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
          <input
            v-model="url"
            type="text"
            placeholder="粘贴视频链接"
            class="flex-1 bg-transparent border-none focus:ring-0 outline-none text-white text-base py-3.5 placeholder:text-disabled"
            @keyup.enter="handleParse"
            @input="onUrlInput"
          />
        </div>
        <button
          class="gradient-bg border-none rounded-[1.5rem] px-7 py-3.5 text-onAccent font-bold cursor-pointer transition-all duration-200 ease-out hover:brightness-110 hover:-translate-y-0.5 hover:shadow-glow disabled:hover:translate-y-0 disabled:hover:shadow-none disabled:opacity-80 flex items-center gap-2 flex-shrink-0"
          :disabled="loading"
          @click="handleParse"
        >
          <svg
            v-if="loading"
            class="animate-spin"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
          >
            <path d="M21 12a9 9 0 1 1-6.219-8.56" stroke-linecap="round"/>
          </svg>
          {{ loading ? '解析中...' : '解析视频' }}
          <svg v-if="!loading" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        </button>
      </div>

      <!-- ErrE: 三色分级错误 banner(根据 errorCode 选 variant) -->
      <div
        v-if="error"
        :class="['mt-3 px-3 py-2.5 rounded-btn border text-sm flex items-start gap-2', variant.bg, variant.border, variant.text]"
        role="alert"
      >
        <!-- icon: 按 variant 切换 -->
        <svg
          v-if="variant.icon === 'alert'"
          class="w-4 h-4 mt-0.5 flex-shrink-0"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
        >
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <svg
          v-else-if="variant.icon === 'warning'"
          class="w-4 h-4 mt-0.5 flex-shrink-0"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
        >
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <svg
          v-else
          class="w-4 h-4 mt-0.5 flex-shrink-0"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
        >
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="16" x2="12" y2="12"/>
          <line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>

        <span class="flex-1">{{ error }}</span>

        <!-- ErrG: 可重试错误显示重试按钮 -->
        <button
          v-if="variant.retryable"
          @click="handleParse"
          :disabled="loading"
          class="ml-1 text-xs font-medium underline underline-offset-2 hover:no-underline disabled:opacity-50 disabled:cursor-not-allowed"
        >
          重试
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { VideoInfo } from '~/types'

const emit = defineEmits<{
  parsed: [videoInfo: VideoInfo]
}>()

const url = ref('')
const loading = ref(false)
const error = ref('')
// ErrE: 记录 error code 用于样式分级 + retryable 判断
const errorCode = ref<string>('')

// ErrE: error code → 视觉变体(red/yellow/blue)+ icon 类型 + 是否可重试
const ERROR_VARIANTS: Record<string, {
  bg: string
  border: string
  text: string
  icon: 'alert' | 'warning' | 'info'
  retryable: boolean
}> = {
  // error 红色 - 硬错误,需要用户改链接/登录
  video_not_found:    { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-300',    icon: 'alert',   retryable: false },
  auth_required:      { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-300',    icon: 'alert',   retryable: false },
  video_unavailable:  { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-300',    icon: 'alert',   retryable: false },
  video_private:      { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-300',    icon: 'alert',   retryable: false },
  unsupported_url:    { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-300',  icon: 'warning', retryable: false },
  parse_failed:       { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-300',    icon: 'alert',   retryable: true  },
  http_error:         { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-300',    icon: 'alert',   retryable: true  },
  access_denied:      { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-300',    icon: 'alert',   retryable: false },

  // warning 黄色 - 临时性错误,可以自动重试
  rate_limited:       { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-300',  icon: 'warning', retryable: true  },
  network_error:      { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-300',  icon: 'warning', retryable: true  },
  anti_scraping:      { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-300',  icon: 'warning', retryable: true  },

  // info 蓝色 - 输入格式/使用引导
  empty_url:          { bg: 'bg-blue-500/10',    border: 'border-blue-500/30',    text: 'text-blue-300',   icon: 'info',    retryable: false },
  invalid_url_format: { bg: 'bg-blue-500/10',    border: 'border-blue-500/30',    text: 'text-blue-300',   icon: 'info',    retryable: false },
}

const DEFAULT_VARIANT = {
  bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-300',
  icon: 'alert' as const, retryable: true,
}

const variant = computed(() =>
  ERROR_VARIANTS[errorCode.value] || DEFAULT_VARIANT
)

const config = useRuntimeConfig()
const apiBase = config.public.apiBase

// Extract a URL from pasted text (e.g. Douyin share messages)
function extractUrl(text: string): string {
  const trimmed = text.trim().replace(/[`]/g, '')
  // If it's already a clean URL, return as-is
  if (/^https?:\/\//.test(trimmed)) return trimmed
  // Find the first URL in the text
  const match = trimmed.match(/https?:\/\/[^\s]+/)
  if (match) return match[0]
  return trimmed
}

// ErrF: 用户在 input 框里继续输入时自动清除旧错误
// ——避免红色 banner 干扰用户的下一次尝试
function onUrlInput() {
  if (error.value) {
    error.value = ''
    errorCode.value = ''
  }
}

const handleParse = async () => {
  const input = extractUrl(url.value)
  if (!input) {
    error.value = '请输入视频链接'
    errorCode.value = 'empty_url'
    return
  }

  // Update input field with extracted URL
  url.value = input
  loading.value = true
  error.value = ''
  errorCode.value = ''

  try {
    const response = await $fetch<VideoInfo>(`${apiBase}/api/parse`, {
      method: 'POST',
      body: { url: input }
    })
    emit('parsed', response)
  } catch (e: any) {
    // ErrC: 后端 detail 现在是 {code, message} dict;旧版本可能还是 string
    const detail = e?.data?.detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      error.value = String(detail.message)
      errorCode.value = String(detail.code || 'parse_failed')
    } else if (typeof detail === 'string' && detail) {
      error.value = detail
      errorCode.value = 'parse_failed'
    } else {
      error.value = '解析失败,请检查链接是否正确,或稍后重试。'
      errorCode.value = 'parse_failed'
    }
  } finally {
    loading.value = false
  }
}
</script>
