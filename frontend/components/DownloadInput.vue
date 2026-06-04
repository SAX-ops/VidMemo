<template>
  <div class="max-w-2xl mx-auto">
    <div class="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-2xl">
      <div class="flex gap-3 mb-5">
        <input
          v-model="url"
          type="text"
          placeholder="粘贴视频链接，例如 https://youtube.com/watch?v=..."
          class="flex-1 bg-white/5 border-2 border-white/15 rounded-xl px-5 py-4 text-white text-base outline-none transition-all focus:border-primary-from focus:shadow-[0_0_20px_rgba(255,107,107,0.2)] placeholder:text-gray-600"
          @keyup.enter="handleParse"
        />
        <button
          class="gradient-bg border-none rounded-xl px-8 py-4 text-white text-lg font-bold cursor-pointer transition-all hover:-translate-y-1 hover:shadow-[0_12px_32px_rgba(255,107,107,0.5)] disabled:hover:translate-y-0 disabled:hover:shadow-none disabled:opacity-80 flex items-center gap-2"
          :disabled="loading"
          @click="handleParse"
        >
          <svg
            v-if="loading"
            class="animate-spin"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
          >
            <path d="M21 12a9 9 0 1 1-6.219-8.56" stroke-linecap="round"/>
          </svg>
          {{ loading ? '解析中...' : '解析视频' }}
        </button>
      </div>

      <div v-if="error" class="text-red-400 text-sm mt-2">
        {{ error }}
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

const handleParse = async () => {
  const input = extractUrl(url.value)
  if (!input) {
    error.value = '请输入视频链接'
    return
  }

  // Update input field with extracted URL
  url.value = input
  loading.value = true
  error.value = ''

  try {
    const response = await $fetch<VideoInfo>(`${apiBase}/api/parse`, {
      method: 'POST',
      body: { url: input }
    })
    emit('parsed', response)
  } catch (e: any) {
    error.value = e.data?.detail || '解析失败，请检查链接是否正确'
  } finally {
    loading.value = false
  }
}
</script>
