<template>
  <div v-if="visible" class="bg-dark-card border border-dark-border rounded-2xl overflow-hidden mt-6">
    <!-- Tab nav -->
    <div class="flex border-b border-dark-border">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'flex items-center gap-2 px-5 py-3 text-sm font-medium transition-all',
          activeTab === tab.key ? 'text-primary-from border-b-2 border-primary-from' : 'text-text-secondary hover:text-white',
        ]"
      >
        <span>{{ tab.icon }}</span>
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <!-- Content -->
    <div class="p-6 min-h-[300px]">
      <!-- Summary tab -->
      <div v-show="activeTab === 'summary'">
        <!-- Banner slots -->
        <div v-if="languageBanner" class="mb-3 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-300 text-sm">
          {{ languageBanner }}
        </div>
        <div v-if="fallbackBanner" class="mb-3 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-300 text-sm">
          {{ fallbackBanner }}
        </div>
        <div v-if="cacheBadge" class="mb-3 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-300 text-xs">
          ✓ 来自缓存 ({{ cacheBadge }})
        </div>

        <!-- Chapter list (from JSON event) -->
        <div v-if="chapters.length > 0" class="mb-4">
          <h3 class="text-sm font-semibold text-text-secondary mb-2">章节</h3>
          <ol class="space-y-1">
            <li
              v-for="(ch, idx) in chapters"
              :key="idx"
              class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-dark-bg/50 cursor-pointer transition-colors"
              @click="onChapterClick(ch.time)"
            >
              <span class="text-primary-from font-mono text-xs min-w-[50px]">{{ formatTime(ch.time) }}</span>
              <span class="text-white text-sm">{{ ch.title }}</span>
            </li>
          </ol>
        </div>

        <!-- Summary markdown (rendered) -->
        <div v-if="summaryText" class="prose prose-invert prose-sm max-w-none" v-html="renderedSummary" />
        <div v-else-if="loading" class="flex flex-col items-center py-12 gap-3">
          <div class="w-10 h-10 border-4 border-white/20 border-t-primary-from rounded-full animate-spin" />
          <span class="text-text-secondary text-sm">{{ loadingMessage }}</span>
        </div>
        <div v-else-if="errorMessage" class="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {{ errorMessage }}
        </div>
      </div>

      <!-- Subtitle tab -->
      <div v-show="activeTab === 'subtitle'">
        <div v-if="subtitleData.segments.length > 0" class="space-y-1 max-h-[500px] overflow-y-auto">
          <div
            v-for="(seg, idx) in subtitleData.segments"
            :key="idx"
            class="flex gap-3 py-1.5 px-2 rounded hover:bg-dark-bg/30"
          >
            <span class="text-primary-from font-mono text-xs pt-1 min-w-[50px]">{{ formatTime(seg.start) }}</span>
            <span class="text-white text-sm">{{ seg.text }}</span>
          </div>
        </div>
        <div v-else class="text-text-secondary text-sm text-center py-12">该视频暂无可用字幕</div>
      </div>

      <!-- Mindmap tab (placeholder) -->
      <div v-show="activeTab === 'mindmap'" class="text-center py-12 text-text-secondary text-sm">
        思维导图将在下一迭代提供
      </div>

      <!-- Q&A tab (placeholder) -->
      <div v-show="activeTab === 'qa'" class="text-center py-12 text-text-secondary text-sm">
        AI 问答将在下一迭代提供
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { marked } from 'marked'
import type { SubtitleData, Chapter as ChapterT } from '~/types'
import { useSSE } from '~/composables/useSSE'

const props = defineProps<{
  visible: boolean
  videoUrl: string
  videoTitle?: string
}>()

const emit = defineEmits<{
  'chapter-click': [timeSec: number]
  'loading-change': [loading: boolean]
}>()

// ... state and methods (added in next steps)
const tabs = [
  { key: 'summary', label: '总结摘要', icon: '📝' },
  { key: 'subtitle', label: '字幕文本', icon: '📄' },
  { key: 'mindmap', label: '思维导图', icon: '🧠' },
  { key: 'qa', label: 'AI 问答', icon: '💬' },
] as const
const activeTab = ref<typeof tabs[number]['key']>('summary')

const summaryText = ref('')
const chapters = ref<ChapterT[]>([])
const subtitleData = ref<SubtitleData>({
  has_subtitle: false,
  language: '',
  subtitle_type: 'none',
  is_target_language: true,
  segments: [],
  full_text: '',
})

const loading = ref(false)
const loadingMessage = ref('正在提取视频字幕...')
const errorMessage = ref('')
const cacheBadge = ref('')
const languageBanner = computed(() =>
  subtitleData.value.has_subtitle && !subtitleData.value.is_target_language
    ? `字幕为 ${subtitleData.value.language}，已按原文总结（未翻译）`
    : ''
)
const fallbackBanner = computed(() =>
  subtitleData.value.fallback_mode === 'metadata'
    ? '该视频无字幕，本总结基于标题生成（精度有限）'
    : ''
)

const renderedSummary = computed(() => summaryText.value ? marked.parse(summaryText.value) as string : '')

let currentAbort: (() => void) | null = null

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

function onChapterClick(t: number) {
  emit('chapter-click', t)
}

function startStream() {
  // Abort any existing stream before starting a new one
  if (currentAbort) {
    currentAbort()
    currentAbort = null
  }
  // Reset state
  summaryText.value = ''
  chapters.value = []
  errorMessage.value = ''
  cacheBadge.value = ''
  subtitleData.value = {
    has_subtitle: false, language: '', subtitle_type: 'none',
    is_target_language: true, segments: [], full_text: '',
  }
  loading.value = true
  loadingMessage.value = '正在提取视频字幕...'

  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase || ''

  const { abort } = useSSE(
    `${apiBase}/api/summarize`,
    { url: props.videoUrl, language: 'zh' },
    {
      cache_hit: (data: any) => {
        cacheBadge.value = data.cached_at
        summaryText.value = data.summary
        chapters.value = data.chapters || []
        subtitleData.value = { ...subtitleData.value, ...(data.subtitle_meta || {}) }
        loading.value = false
        loadingMessage.value = '已从缓存加载'
      },
      subtitle: (data: any) => {
        subtitleData.value = data
        if (data.fallback_mode === 'metadata') {
          loadingMessage.value = '正在基于元数据生成总结...'
        } else if (data.has_subtitle) {
          loadingMessage.value = 'AI 正在分析视频内容...'
        }
      },
      summary: (data: any) => {
        summaryText.value += typeof data === 'string' ? data : JSON.stringify(data)
      },
      chapters: (data: any) => {
        chapters.value = data.chapters || []
      },
      done: () => {
        loading.value = false
        emit('loading-change', false)
      },
      error: (data: any) => {
        loading.value = false
        errorMessage.value = data?.message || '总结失败'
        emit('loading-change', false)
      },
    }
  )
  currentAbort = abort
}

watch(
  () => props.visible,
  (v) => { if (v) startStream() }
)

onMounted(() => {
  if (props.visible) startStream()
})

onBeforeUnmount(() => {
  if (currentAbort) {
    currentAbort()
    currentAbort = null
  }
})
</script>
