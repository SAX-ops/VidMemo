<template>
  <div v-if="progress" class="bg-dark-card border border-dark-border rounded-card p-6 shadow-card">

    <!-- triggered 终态: 蓝色 ✓ "文件已开始下载到您的电脑" -->
    <div v-if="downloadState === 'triggered'" class="flex items-center gap-3">
      <div class="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center flex-shrink-0">
        <svg class="w-5 h-5 text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
      </div>
      <div class="flex-1">
        <p class="text-blue-400 text-sm font-semibold">文件已开始下载到您的电脑</p>
        <p class="text-secondary text-xs mt-0.5">请查看浏览器下载列表确认保存进度</p>
      </div>
      <button
        class="flex-shrink-0 px-4 py-2 rounded-btn text-sm font-medium transition-all duration-200 ease-out bg-dark-bg border border-dark-border text-secondary hover:border-primary-from/50 hover:text-primary"
        @click="$emit('re-download')"
      >
        重新下载
      </button>
    </div>

    <!-- preparing: 蓝色 spinner "文件已准备完成,正在传输到浏览器..." -->
    <div v-else-if="downloadState === 'preparing'" class="flex items-center gap-3">
      <div class="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center flex-shrink-0">
        <svg class="w-5 h-5 text-blue-400 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" stroke-linecap="round"/></svg>
      </div>
      <div class="flex-1">
        <p class="text-blue-400 text-sm font-semibold">文件已准备完成,正在传输到浏览器...</p>
        <p class="text-secondary text-xs mt-0.5">正在从服务器获取文件,大文件可能需要等待数秒</p>
      </div>
    </div>

    <!-- failed: 红色 ✕ -->
    <div v-else-if="downloadState === 'failed'" class="flex items-center gap-3">
      <div class="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center flex-shrink-0">
        <svg class="w-5 h-5 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
      </div>
      <div class="flex-1">
        <p class="text-red-400 text-sm font-semibold">下载失败</p>
        <p class="text-secondary text-xs mt-0.5">文件传输失败,请检查网络后重试</p>
      </div>
      <button
        class="flex-shrink-0 px-4 py-2 rounded-btn text-sm font-medium transition-all duration-200 ease-out gradient-bg text-onAccent font-bold hover:-translate-y-0.5 hover:shadow-glow"
        @click="$emit('re-download')"
      >
        重试
      </button>
    </div>

    <!-- idle: 进度条 + 百分比 + 状态信息 -->
    <template v-else>
      <div class="flex justify-between mb-3 text-sm">
        <span class="text-white truncate mr-3">{{ filename }}</span>
        <span class="text-primary-from font-semibold flex-shrink-0">{{ Math.round(displayProgress) }}%</span>
      </div>

      <div class="h-2.5 bg-white/10 rounded-full overflow-hidden">
        <div
          class="h-full gradient-bg rounded-full transition-all duration-300"
          :style="{ width: `${Math.max(displayProgress, 0)}%` }"
        />
      </div>

      <div class="flex justify-between mt-3 text-xs text-tertiary">
        <span>已下载: {{ progress.downloaded }}</span>
        <span>速度: {{ progress.speed }}</span>
        <span>剩余: {{ progress.eta }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { ProgressUpdate } from '~/types'

defineProps<{
  progress: ProgressUpdate
  filename: string
  displayProgress: number
  downloadState: 'idle' | 'preparing' | 'triggered' | 'failed'
}>()

defineEmits<{
  're-download': []
}>()
</script>
