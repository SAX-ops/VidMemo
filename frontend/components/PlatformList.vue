<template>
  <div class="py-16 text-center">
    <h2 class="text-sm text-secondary uppercase tracking-widest mb-3">
      支持 10 个主流平台
    </h2>
    <p class="text-tertiary text-xs mb-8">持续接入中</p>

    <div class="flex justify-center flex-wrap gap-2 max-w-2xl mx-auto">
      <span
        v-for="name in platforms"
        :key="name"
        class="px-4 py-2 rounded-pill bg-white/5 border border-white/10 text-secondary text-sm transition-all duration-200 ease-out hover:border-primary-from/50 hover:text-primary hover:bg-primary-from/10 cursor-default"
      >
        {{ name }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
// P1-5: 9 个平台(以 CLAUDE.md 为准),不再使用 emoji icon 行
const platforms = [
  'YouTube',
  'B 站',
  'TikTok',
  '抖音',
  'Instagram',
  '小红书',
  'X (Twitter)',
  'Facebook',
  '微博',
  '西瓜视频',
]
</script>
