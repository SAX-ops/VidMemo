<template>
  <div class="flex flex-col h-full">
    <!-- Messages -->
    <div ref="messagesEl" class="flex-1 overflow-y-auto space-y-4 mb-4 px-1">
      <!-- Empty state -->
      <div v-if="messages.length === 0" class="flex flex-col items-center justify-center py-12 gap-4 text-center">
        <p class="text-text-secondary text-sm">💬 基于视频内容的智能问答</p>
        <div class="space-y-2 w-full max-w-md">
          <p class="text-text-secondary/60 text-xs">示例问题：</p>
          <button
            v-for="q in exampleQuestions"
            :key="q"
            @click="askQuestion(q)"
            class="block w-full text-left px-4 py-2.5 rounded-lg bg-dark-bg/50 hover:bg-dark-bg/80 text-text-secondary text-sm transition-colors"
          >
            {{ q }}
          </button>
        </div>
      </div>

      <!-- Message list -->
      <div v-for="(msg, idx) in messages" :key="idx">
        <!-- User message -->
        <div v-if="msg.role === 'user'" class="flex justify-end">
          <div class="bg-primary-from/20 text-white text-sm px-4 py-2.5 rounded-2xl rounded-br-sm max-w-[85%]">
            {{ msg.content }}
          </div>
        </div>

        <!-- Assistant message -->
        <div v-else class="flex flex-col gap-2 max-w-[90%]">
          <div class="text-text-secondary text-sm leading-relaxed whitespace-pre-wrap">
            <span v-if="msg.content">{{ msg.content }}</span>
            <span v-else-if="status === 'generating' && idx === currentAssistantIdx" class="inline-flex items-center gap-1.5">
              <span class="w-1.5 h-1.5 bg-primary-from rounded-full animate-pulse" />
              <span class="w-1.5 h-1.5 bg-primary-from rounded-full animate-pulse [animation-delay:0.2s]" />
              <span class="w-1.5 h-1.5 bg-primary-from rounded-full animate-pulse [animation-delay:0.4s]" />
            </span>
          </div>

          <!-- Citation cards -->
          <div v-if="msg.citations?.length" class="mt-1">
            <p class="text-xs text-text-secondary/60 mb-1">📎 来源</p>
            <div class="space-y-1">
              <button
                v-for="(cit, ci) in msg.citations"
                :key="ci"
                @click="emit('seek', cit.timestamp)"
                class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-dark-bg/40 hover:bg-dark-bg/70 transition-colors w-full text-left"
              >
                <span class="text-primary-from font-mono text-xs min-w-[42px]">
                  {{ formatTime(cit.timestamp) }}
                </span>
                <span class="text-text-secondary text-sm">{{ cit.chapter_title }}</span>
              </button>
            </div>
          </div>

          <!-- Cancelled badge -->
          <div v-if="status === 'cancelled' && idx === currentAssistantIdx" class="text-xs text-text-secondary/40 mt-0.5">
            已取消
          </div>
        </div>
      </div>
    </div>

    <!-- Input area -->
    <div class="border-t border-dark-border pt-3">
      <div class="flex gap-2">
        <input
          v-model="input"
          :disabled="status === 'generating'"
          @keydown.enter="handleSend"
          placeholder="输入你的问题..."
          class="flex-1 bg-dark-bg/60 border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-text-secondary/40 focus:outline-none focus:border-primary-from/50 disabled:opacity-40"
        />
        <button
          v-if="status === 'generating'"
          @click="handleStop"
          class="px-4 py-2 rounded-lg bg-red-500/20 text-red-400 text-sm hover:bg-red-500/30 transition-colors"
        >
          停止
        </button>
        <button
          v-else
          @click="handleSend"
          :disabled="!input.trim()"
          class="px-4 py-2 rounded-lg bg-primary-from text-dark-bg text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-30"
        >
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onBeforeUnmount } from 'vue'
import type { Citation, ChatMessage, ChatStatus } from '~/types'
import { useSSE } from '~/composables/useSSE'

const props = defineProps<{
  videoUrl: string
}>()

const emit = defineEmits<{
  seek: [timeSec: number]
}>()

// State
const messages = ref<ChatMessage[]>([])
const input = ref('')
const status = ref<ChatStatus>('idle')
const currentAssistantIdx = ref<number | null>(null)
let currentAbort: (() => void) | null = null

const messagesEl = ref<HTMLDivElement | null>(null)

const exampleQuestions = [
  '这个项目用了什么技术栈？',
  '作者是怎么开发这个项目的？',
  '项目最终如何部署？',
]

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value) {
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    }
  })
}

function askQuestion(q: string) {
  input.value = q
  handleSend()
}

function handleSend() {
  const question = input.value.trim()
  if (!question || status.value === 'generating') return

  // Add user message
  messages.value.push({ role: 'user', content: question })
  input.value = ''

  // Add assistant placeholder
  messages.value.push({ role: 'assistant', content: '' })
  currentAssistantIdx.value = messages.value.length - 1
  status.value = 'generating'
  scrollToBottom()

  // Start SSE
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase || ''

  const { abort } = useSSE(
    `${apiBase}/api/chat`,
    { url: props.videoUrl, question },
    {
      chat_token: (data: unknown) => {
        const token = String(data)
        const idx = currentAssistantIdx.value
        if (idx !== null && idx < messages.value.length) {
          messages.value[idx].content += token
          scrollToBottom()
        }
      },
      chat_done: (data: unknown) => {
        const payload = data as { citations?: Citation[] }
        const idx = currentAssistantIdx.value
        if (idx !== null && idx < messages.value.length) {
          // Strip [[CH_N]] markers from accumulated text
          messages.value[idx].content = messages.value[idx].content
            .replace(/\s*\[\[CH_\d+\]\]\s*/g, ' ')
            .replace(/\s{2,}/g, ' ')
            .trim()
          messages.value[idx].citations = payload.citations || []
        }
        status.value = 'success'
        currentAssistantIdx.value = null
        scrollToBottom()
      },
      chat_error: (data: unknown) => {
        const payload = data as { message?: string }
        const idx = currentAssistantIdx.value
        if (idx !== null && idx < messages.value.length) {
          messages.value[idx].content = payload.message || '回答失败'
        }
        status.value = 'error'
        currentAssistantIdx.value = null
      },
    },
  )
  currentAbort = abort
}

function handleStop() {
  if (currentAbort) {
    currentAbort()
    currentAbort = null
  }
  status.value = 'cancelled'
  // Keep currentAssistantIdx so the "已取消" badge can match it
}

// Clean up on unmount
onBeforeUnmount(() => {
  if (currentAbort) {
    currentAbort()
    currentAbort = null
  }
})
</script>
