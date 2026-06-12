<template>
  <div v-if="visible" data-testid="video-summary-panel" class="bg-dark-card border border-dark-border rounded-card overflow-hidden shadow-card flex flex-col" :style="height ? { height: height + 'px' } : undefined">
    <!-- Tab nav -->
    <div class="flex border-b border-dark-border">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'flex items-center gap-2 px-5 py-3 text-sm font-medium transition-all duration-200 ease-out',
          activeTab === tab.key ? 'text-primary-from border-b-2 border-primary-from' : 'text-secondary hover:text-primary',
        ]"
      >
        <!-- P1-4: 16px lucide-style stroke icon(替代 emoji) -->
        <svg
          v-if="tab.key === 'summary'"
          width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M8 2v4"/><path d="M16 2v4"/><rect width="16" height="18" x="4" y="4" rx="2"/>
          <path d="M8 10h6"/><path d="M8 14h8"/><path d="M8 18h5"/>
        </svg>
        <svg
          v-else-if="tab.key === 'subtitle'"
          width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>
          <path d="M14 2v4a2 2 0 0 0 2 2h4"/>
          <path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>
        </svg>
        <svg
          v-else-if="tab.key === 'mindmap'"
          width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M12 5a3 3 0 1 0-5.997.142 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
          <path d="M12 5a3 3 0 1 1 5.997.142 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
          <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>
        </svg>
        <svg
          v-else-if="tab.key === 'qa'"
          width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>
        </svg>
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <!-- 内容区独立滚动，flex-1 填满卡片剩余高度 -->
    <div class="p-6 flex-1 overflow-y-auto min-h-0">
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
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline -mt-0.5 mr-1"><polyline points="20 6 9 17 4 12"/></svg>来自缓存 ({{ cacheBadge }})
        </div>

        <!-- Loading spinner (initial phase: extracting subtitles / generating outline) -->
        <div v-if="loading" class="flex flex-col items-center py-12 gap-3">
          <div class="w-10 h-10 border-4 border-white/20 border-t-primary-from rounded-full animate-spin" />
          <span class="text-secondary text-sm">{{ loadingMessage }}</span>
        </div>

        <!-- Error -->
        <div v-if="errorMessage" class="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm mb-4">
          {{ errorMessage }}
        </div>

        <!-- Export actions -->
        <div v-if="outline.length > 0" class="mb-4 pb-3 border-b border-dark-border flex items-center justify-between" data-testid="summary-export-bar">
          <span class="text-xs text-tertiary">导出总结内容</span>
          <div class="flex items-center gap-1.5">
            <button
              @click="copyToClipboard(getExportMarkdown(), 'summary')"
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-secondary hover:text-white hover:bg-white/5 transition-colors"
              data-testid="copy-summary-btn"
            >
              <svg v-if="copySuccess === 'summary'" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
              <span>{{ copySuccess === 'summary' ? '已复制' : '复制' }}</span>
            </button>
            <button
              @click="downloadFile(getExportMarkdown(), safeFilename(props.videoTitle) + '.md', 'text/markdown;charset=utf-8')"
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-secondary hover:text-white hover:bg-white/5 transition-colors"
              data-testid="download-summary-btn"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
              <span>下载 .md</span>
            </button>
          </div>
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
              <span class="text-secondary text-sm">正在生成视频概述...</span>
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
              <h3 class="text-sm font-semibold text-secondary">视频概述</h3>
              <span class="text-xs text-secondary/60">{{ showExecSummary ? '收起' : '查看详情' }}</span>
              <svg class="w-3 h-3 text-secondary/60 transition-transform ml-auto" :class="{ 'rotate-180': showExecSummary }" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
            <div v-show="showExecSummary" class="space-y-3 mt-3">
              <p v-if="executiveSummary.core_topic" class="text-white text-sm font-medium leading-relaxed">{{ executiveSummary.core_topic }}</p>
              <div v-if="executiveSummary.key_insights?.length">
                <p class="text-xs text-secondary mb-1">关键观点</p>
                <ul class="space-y-1">
                  <li v-for="(item, i) in executiveSummary.key_insights" :key="i" class="flex items-start gap-2 text-sm text-secondary">
                    <span class="text-primary-from mt-0.5">•</span>
                    <span class="line-clamp-2">{{ item }}</span>
                  </li>
                </ul>
              </div>
              <div v-if="executiveSummary.author_conclusion">
                <p class="text-xs text-secondary mb-1">作者结论</p>
                <p class="text-sm text-secondary leading-relaxed line-clamp-3">{{ executiveSummary.author_conclusion }}</p>
              </div>
              <div v-if="executiveSummary.controversies?.length">
                <p class="text-xs text-secondary mb-1">争议与讨论</p>
                <ul class="space-y-1">
                  <li v-for="(item, i) in executiveSummary.controversies" :key="i" class="flex items-start gap-2 text-sm text-yellow-300/80">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mt-0.5 flex-shrink-0 text-yellow-300"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                    <span class="line-clamp-2">{{ item }}</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
          <!-- else: execSummaryLoading=false && executiveSummary=null → hidden (quality gate) -->
        </div>

        <!-- Play-3: Outline tree — 章节序号 / 高亮 / 时间戳强化 / hover 提示 -->
        <div v-if="outline.length > 0" data-testid="summary-outline">
          <h3 class="text-sm font-semibold text-secondary mb-3">视频大纲</h3>
          <div class="space-y-2">
            <div
              v-for="(sec, idx) in outline"
              :key="idx"
              :class="['rounded-xl transition-colors duration-300', activeChapterIndex === idx ? 'bg-primary-from/10 ring-1 ring-primary-from/30' : '']"
            >
              <button
                @click="onOutlineClick(sec.timestamp)"
                :class="[
                  'flex items-center gap-3 px-3 py-2.5 w-full text-left transition-all duration-200 ease-out rounded-lg group',
                  activeChapterIndex === idx
                    ? 'hover:bg-primary-from/15'
                    : 'hover:bg-dark-bg/60',
                ]"
              >
                <!-- 序号徽章 -->
                <span
                  :class="[
                    'w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold flex-shrink-0 transition-colors duration-300',
                    activeChapterIndex === idx
                      ? 'bg-primary-from text-dark-bg'
                      : 'bg-white/10 text-secondary',
                  ]"
                >
                  {{ String(idx + 1).padStart(2, '0') }}
                </span>
                <!-- 时间戳 -->
                <span class="text-primary-from font-mono text-sm font-semibold min-w-[44px]">{{ formatTime(sec.timestamp) }}</span>
                <!-- 标题 -->
                <span :class="['text-sm font-medium flex-1 transition-colors duration-300', activeChapterIndex === idx ? 'text-white' : 'text-secondary']">
                  {{ sec.title }}
                </span>
                <!-- hover "跳转" 提示 -->
                <span class="text-xs text-secondary/60 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                  跳转
                </span>
              </button>
              <ul v-if="sec.summary?.length" class="mt-1 ml-10 space-y-1 pb-1">
                <li
                  v-for="(item, pidx) in sec.summary"
                  :key="pidx"
                  class="flex items-start gap-2 px-2"
                >
                  <span class="text-primary-from mt-1.5 w-1.5 h-1.5 rounded-full bg-primary-from/60 flex-shrink-0" />
                  <span class="text-secondary text-sm leading-relaxed">{{ item }}</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <!-- Rendered markdown content -->
        <div v-if="renderedSummary" class="mt-4 pt-4 border-t border-dark-border" data-testid="summary-markdown">
          <div class="prose-summary" v-html="renderedSummary" />
        </div>


      </div>

      <!-- Subtitle tab -->
      <div v-show="activeTab === 'subtitle'" class="flex flex-col flex-1 min-h-0">
        <!-- Subtitle export toolbar -->
        <div v-if="subtitleData.segments.length > 0" class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-secondary">字幕文本</h3>
          <div class="flex items-center gap-1">
            <button
              @click="copyToClipboard(subtitleData.full_text || subtitleData.segments.map(s => s.text).join('\n'), 'subtitle')"
              class="p-1.5 rounded-lg text-secondary hover:text-white hover:bg-white/5 transition-colors"
              :title="copySuccess === 'subtitle' ? '已复制' : '复制字幕'"
              data-testid="copy-subtitle-btn"
            >
              <svg v-if="copySuccess === 'subtitle'" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
            </button>
            <button
              @click="downloadFile(subtitleData.full_text || subtitleData.segments.map(s => s.text).join('\n'), safeFilename(props.videoTitle) + '.txt', 'text/plain;charset=utf-8')"
              class="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-secondary hover:text-white hover:bg-white/5 transition-colors"
              title="下载纯文本字幕"
              data-testid="download-txt-btn"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
              <span>.txt</span>
            </button>
            <button
              @click="downloadFile(generateSRT(subtitleData.segments), safeFilename(props.videoTitle) + '.srt', 'text/plain;charset=utf-8')"
              class="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-secondary hover:text-white hover:bg-white/5 transition-colors"
              title="下载 SRT 字幕（带时间轴）"
              data-testid="download-srt-btn"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
              <span>.srt</span>
            </button>
          </div>
        </div>
        <div v-if="subtitleData.segments.length > 0" class="space-y-1">
          <div
            v-for="(seg, idx) in subtitleData.segments"
            :key="idx"
            class="flex gap-3 py-1.5 px-2 rounded hover:bg-dark-bg/30"
          >
            <span class="text-primary-from font-mono text-xs pt-1 min-w-[50px]">{{ formatTime(seg.start) }}</span>
            <span class="text-white text-sm">{{ seg.text }}</span>
          </div>
        </div>
        <div v-else class="text-secondary text-sm text-center py-12">该视频暂无可用字幕</div>
      </div>

      <!-- Mindmap tab — v-if (not v-show) so MindMap mounts with real
           container dimensions. Under v-show the container is display:none
           when the tab is inactive, which makes Mind-Elixir initialize at
           0×0 and clip all nodes invisibly. -->
      <div v-if="activeTab === 'mindmap'" data-testid="mindmap-pane" class="flex flex-col flex-1 min-h-0">
        <div
          v-if="mindmapLoading && !mindmap"
          class="flex flex-col items-center py-12 gap-3"
          data-testid="mindmap-loading"
        >
          <div class="w-10 h-10 border-4 border-white/20 border-t-primary-from rounded-full animate-spin" />
          <span class="text-secondary text-sm">正在生成思维导图...</span>
        </div>
        <MindMap
          v-else-if="mindmap"
          :data="mindmap"
          @node-click="onOutlineClick"
          data-testid="mindmap"
        />
        <div
          v-else
          class="text-center py-12 text-secondary text-sm"
          data-testid="mindmap-empty"
        >
          该视频暂未生成思维导图
        </div>
      </div>

      <!-- Q&A tab -->
      <div v-show="activeTab === 'qa'" data-testid="chat-pane" class="flex flex-col flex-1 min-h-0">
        <ChatPanel
          v-if="canChat"
          :video-url="videoUrl"
          @seek="onOutlineClick"
        />
        <div v-else class="flex flex-col items-center justify-center py-12 gap-2 text-center">
          <p class="text-secondary text-sm flex items-center gap-1.5"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg> 该视频无可用字幕，无法进行问答。</p>
          <p class="text-secondary/60 text-xs">请查看「字幕文本」标签页确认。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { marked } from 'marked'
import type { SubtitleData, OutlineSection as OutlineSectionT, ExecutiveSummary, MindmapData } from '~/types'
import { useSSE } from '~/composables/useSSE'
import { currentTime as sharedCurrentTime, isPlaying as sharedIsPlaying } from '~/composables/usePlaybackState'
import { formatSRTTime, generateSRT, safeFilename, generateFullSummary, formatTime as formatTimeUtil } from '~/composables/useExport'
import MindMap from '~/components/MindMap.vue'
import ChatPanel from '~/components/ChatPanel.vue'

const props = defineProps<{
  visible: boolean
  videoUrl: string
  videoTitle?: string
  height?: number
}>()

const emit = defineEmits<{
  'outline-click': [timeSec: number]
  'loading-change': [loading: boolean]
}>()

// ... state and methods (added in next steps)
// P1-4: icon 字段已废弃(改用 v-if 内联 SVG),保留 key+label
const tabs = [
  { key: 'summary', label: '总结摘要' },
  { key: 'subtitle', label: '字幕文本' },
  { key: 'mindmap', label: '思维导图' },
  { key: 'qa', label: 'AI 问答' },
] as const
const activeTab = ref<typeof tabs[number]['key']>('summary')

const outline = ref<OutlineSectionT[]>([])
// Play-3: 计算当前播放时间落入哪个章节(index)
const activeChapterIndex = computed<number | null>(() => {
  if (!sharedIsPlaying.value || !outline.value.length) return null
  const t = sharedCurrentTime.value
  // 找最后一个 timestamp <= currentTime 的章节
  for (let i = outline.value.length - 1; i >= 0; i--) {
    if (outline.value[i].timestamp <= t) return i
  }
  return null
})
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

// Content export state
const summaryMd = ref('')
const renderedSummary = computed(() => {
  if (!summaryMd.value) return ''
  // Explicitly synchronous — avoids string | Promise<string> ambiguity in marked v18
  return marked.parse(summaryMd.value, { async: false }) as string
})
const copySuccess = ref<'summary' | 'subtitle' | null>(null)

let currentAbort: (() => void) | null = null

// --- Export helpers ---

function copyToClipboard(text: string, label: 'summary' | 'subtitle') {
  navigator.clipboard.writeText(text).then(() => {
    copySuccess.value = label
    setTimeout(() => { copySuccess.value = null }, 2000)
  }).catch(() => {
    // Fallback for non-HTTPS or blocked clipboard
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copySuccess.value = label
    setTimeout(() => { copySuccess.value = null }, 2000)
  })
}

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// Generate complete summary markdown for export
function getExportMarkdown(): string {
  return generateFullSummary(outline.value, executiveSummary.value, props.videoTitle, formatTimeUtil)
}

// formatTime used in template — delegate to composable
const formatTime = formatTimeUtil

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
  summaryMd.value = ''
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
        summaryMd.value = data.summary_md || ''
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
      summary_md: (data: unknown) => {
        summaryMd.value = String(data || '')
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

// P2-Layout: 解析新视频(URL 变化)时强制重 stream,避免二次解析后
// 旧视频的总结内容残留在新面板上。
watch(
  () => props.videoUrl,
  (newUrl, oldUrl) => {
    if (newUrl && newUrl !== oldUrl) {
      startStream()
    }
  }
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
