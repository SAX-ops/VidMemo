<template>
  <div v-if="visible" data-testid="video-summary-panel" class="bg-dark-card border border-dark-border rounded-2xl overflow-hidden mt-6">
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

        <!-- Loading spinner (initial phase: extracting subtitles / generating outline) -->
        <div v-if="loading" class="flex flex-col items-center py-12 gap-3">
          <div class="w-10 h-10 border-4 border-white/20 border-t-primary-from rounded-full animate-spin" />
          <span class="text-text-secondary text-sm">{{ loadingMessage }}</span>
        </div>

        <!-- Error -->
        <div v-if="errorMessage" class="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm mb-4">
          {{ errorMessage }}
        </div>

        <!-- Executive Summary — always rendered when outline exists (skeleton or real content) -->
        <div v-if="outline.length > 0" class="mb-4" data-testid="executive-summary-wrapper">
          <!-- Skeleton: waiting for Stage 2 LLM -->
          <div
            v-if="execSummaryLoading && !executiveSummary"
            class="border border-white/10 rounded-lg p-4 bg-white/5"
          >
            <div class="flex items-center gap-3">
              <div class="w-4 h-4 border-2 border-white/20 border-t-primary-from rounded-full animate-spin" />
              <span class="text-text-secondary text-sm">正在生成视频概述...</span>
            </div>
          </div>

          <!-- Real content -->
          <div
            v-else-if="executiveSummary && (executiveSummary.core_topic || executiveSummary.key_insights?.length || executiveSummary.author_conclusion)"
            class="border border-white/10 rounded-lg p-3 bg-white/5"
            data-testid="executive-summary"
          >
            <button
              @click="showExecSummary = !showExecSummary"
              class="flex items-center gap-2 w-full text-left group"
            >
              <h3 class="text-sm font-semibold text-text-secondary">视频概述</h3>
              <span class="text-xs text-text-secondary/60">{{ showExecSummary ? '收起' : '查看详情' }}</span>
              <svg class="w-3 h-3 text-text-secondary/60 transition-transform ml-auto" :class="{ 'rotate-180': showExecSummary }" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
            <div v-show="showExecSummary" class="space-y-3 mt-3">
              <p v-if="executiveSummary.core_topic" class="text-white text-sm font-medium leading-relaxed">{{ executiveSummary.core_topic }}</p>
              <div v-if="executiveSummary.key_insights?.length">
                <p class="text-xs text-text-secondary mb-1">关键观点</p>
                <ul class="space-y-1">
                  <li v-for="(item, i) in executiveSummary.key_insights" :key="i" class="flex items-start gap-2 text-sm text-text-secondary">
                    <span class="text-primary-from mt-0.5">•</span>
                    <span class="line-clamp-2">{{ item }}</span>
                  </li>
                </ul>
              </div>
              <div v-if="executiveSummary.author_conclusion">
                <p class="text-xs text-text-secondary mb-1">作者结论</p>
                <p class="text-sm text-text-secondary leading-relaxed line-clamp-3">{{ executiveSummary.author_conclusion }}</p>
              </div>
              <div v-if="executiveSummary.controversies?.length">
                <p class="text-xs text-text-secondary mb-1">争议与讨论</p>
                <ul class="space-y-1">
                  <li v-for="(item, i) in executiveSummary.controversies" :key="i" class="flex items-start gap-2 text-sm text-yellow-300/80">
                    <span class="mt-0.5">⚡</span>
                    <span class="line-clamp-2">{{ item }}</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
          <!-- else: execSummaryLoading=false && executiveSummary=null → hidden (quality gate) -->
        </div>

        <!-- Outline tree (from JSON event) -->
        <div v-if="outline.length > 0" data-testid="summary-outline">
          <h3 class="text-sm font-semibold text-text-secondary mb-2">视频大纲</h3>
          <div class="space-y-3">
            <div v-for="(sec, idx) in outline" :key="idx">
              <button
                @click="onOutlineClick(sec.timestamp)"
                class="flex items-center gap-3 px-3 py-2 rounded-lg bg-dark-bg/30 hover:bg-dark-bg/60 w-full text-left transition-colors"
              >
                <span class="text-primary-from font-mono text-xs min-w-[50px]">{{ formatTime(sec.timestamp) }}</span>
                <span class="text-white text-sm font-medium">{{ sec.title }}</span>
              </button>
              <ul v-if="sec.summary?.length" class="mt-1 ml-12 space-y-0.5">
                <li
                  v-for="(item, pidx) in sec.summary"
                  :key="pidx"
                  class="flex items-start gap-3 px-3 py-1.5"
                >
                  <span class="text-text-secondary text-sm">{{ item }}</span>
                </li>
              </ul>
            </div>
          </div>
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

      <!-- Mindmap tab — v-if (not v-show) so MindMap mounts with real
           container dimensions. Under v-show the container is display:none
           when the tab is inactive, which makes Mind-Elixir initialize at
           0×0 and clip all nodes invisibly. -->
      <div v-if="activeTab === 'mindmap'" data-testid="mindmap-pane">
        <div
          v-if="mindmapLoading && !mindmap"
          class="flex flex-col items-center py-12 gap-3"
          data-testid="mindmap-loading"
        >
          <div class="w-10 h-10 border-4 border-white/20 border-t-primary-from rounded-full animate-spin" />
          <span class="text-text-secondary text-sm">正在生成思维导图...</span>
        </div>
        <MindMap
          v-else-if="mindmap"
          :data="mindmap"
          @node-click="onOutlineClick"
          data-testid="mindmap"
        />
        <div
          v-else
          class="text-center py-12 text-text-secondary text-sm"
          data-testid="mindmap-empty"
        >
          该视频暂未生成思维导图
        </div>
      </div>

      <!-- Q&A tab -->
      <div v-show="activeTab === 'qa'" data-testid="chat-pane" class="h-[480px]">
        <ChatPanel
          v-if="canChat"
          :video-url="videoUrl"
          @seek="onOutlineClick"
        />
        <div v-else class="flex flex-col items-center justify-center py-12 gap-2 text-center">
          <p class="text-text-secondary text-sm">ℹ️ 该视频无可用字幕，无法进行问答。</p>
          <p class="text-text-secondary/60 text-xs">请查看「字幕文本」标签页确认。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import type { SubtitleData, OutlineSection as OutlineSectionT, ExecutiveSummary, MindmapData } from '~/types'
import { useSSE } from '~/composables/useSSE'
import MindMap from '~/components/MindMap.vue'
import ChatPanel from '~/components/ChatPanel.vue'

const props = defineProps<{
  visible: boolean
  videoUrl: string
  videoTitle?: string
}>()

const emit = defineEmits<{
  'outline-click': [timeSec: number]
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

const outline = ref<OutlineSectionT[]>([])
const executiveSummary = ref<ExecutiveSummary | null>(null)
const mindmap = ref<MindmapData | null>(null)
const showExecSummary = ref(false)
const subtitleData = ref<SubtitleData>({
  has_subtitle: false,
  language: '',
  subtitle_type: 'none',
  is_target_language: true,
  segments: [],
  full_text: '',
})

const loading = ref(false)
const execSummaryLoading = ref(false)
const mindmapLoading = ref(false)
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
const canChat = computed(() =>
  subtitleData.value.has_subtitle && subtitleData.value.segments.length > 0
)

let currentAbort: (() => void) | null = null

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

function onOutlineClick(t: number) {
  emit('outline-click', t)
}

function startStream() {
  // Abort any existing stream before starting a new one
  if (currentAbort) {
    currentAbort()
    currentAbort = null
  }
  // Reset state
  outline.value = []
  executiveSummary.value = null
  mindmap.value = null
  showExecSummary.value = true
  errorMessage.value = ''
  cacheBadge.value = ''
  subtitleData.value = {
    has_subtitle: false, language: '', subtitle_type: 'none',
    is_target_language: true, segments: [], full_text: '',
  }
  loading.value = true
  execSummaryLoading.value = false
  mindmapLoading.value = false
  loadingMessage.value = '正在提取视频字幕...'

  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase || ''

  const { abort } = useSSE(
    `${apiBase}/api/summarize`,
    { url: props.videoUrl, language: 'zh' },
    {
      cache_hit: (data: any) => {
        cacheBadge.value = data.cached_at
        outline.value = data.outline || []
        executiveSummary.value = data.executive_summary || null
        mindmap.value = data.mindmap || null
        subtitleData.value = { ...subtitleData.value, ...(data.subtitle_meta || {}) }
        loading.value = false
        execSummaryLoading.value = false
        mindmapLoading.value = false
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
        // Don't accumulate streaming tokens into summaryText —
        // they contain raw JSON that would flash before summary_md arrives.
        // The final clean content comes via the summary_md event.
      },
      outline: (data: any) => {
        outline.value = data.outline || []
        loading.value = false
        execSummaryLoading.value = true
        // Both stage-2 LLM calls (exec summary + mindmap) start when the
        // outline arrives; show the mindmap skeleton until the event lands
        // (or `done` fires, indicating mindmap was skipped — see plan).
        mindmapLoading.value = true
        emit('loading-change', false)
      },
      summary_md: (_data: string) => {
        // Received but not rendered — kept for cache compatibility
      },
      executive_summary: (data: any) => {
        execSummaryLoading.value = false
        if (data?.core_topic) {
          executiveSummary.value = data
        }
      },
      mindmap: (data: any) => {
        mindmapLoading.value = false
        // Defensive: validate shape before assigning (backend already
        // validates, but a corrupt event shouldn't blank the tab).
        if (data && typeof data.root === 'string' && Array.isArray(data.children)) {
          mindmap.value = data
        }
      },
      done: () => {
        loading.value = false
        execSummaryLoading.value = false
        // If we hit `done` without a mindmap event, the backend either
        // skipped it (quality gate failed) or it's disabled — flip the
        // loading flag off so the empty-state copy renders instead of
        // an indefinite spinner.
        mindmapLoading.value = false
        emit('loading-change', false)
      },
      error: (data: any) => {
        loading.value = false
        execSummaryLoading.value = false
        mindmapLoading.value = false
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
