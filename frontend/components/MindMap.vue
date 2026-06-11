<template>
  <!-- No <ClientOnly> wrapper. Vue's onMounted only fires client-side, and
       the mind-elixir module is loaded via dynamic import() inside mount()
       — never touched on the SSR pass. <ClientOnly> would push the ref div
       into Suspense's fallback and leave `container.value` null when
       onMounted runs, so the mindmap silently never initializes. -->
  <div
    ref="container"
    data-testid="mindmap-container"
    class="mindmap-canvas w-full rounded-xl border border-dark-border bg-dark-bg/40 overflow-hidden"
    :style="{ height: heightPx + 'px' }"
  />
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { MindmapData, MindmapNode } from '~/types'

const props = withDefaults(
  defineProps<{
    data: MindmapData | null
    heightPx?: number
  }>(),
  { heightPx: 480 },
)

const emit = defineEmits<{
  'node-click': [timeSec: number]
}>()

const container = ref<HTMLDivElement | null>(null)
// id → timestamp lookup. mind-elixir preserves node `id` through its
// selectNodes event, so this is the simplest way to attach domain data
// to a node without relying on undocumented custom-field passthrough.
const timestampById = new Map<string, number>()
// Holds the live MindElixir instance. Typed `any` because the library's
// type exports aren't tree-shake-friendly under Nuxt's bundler.
let me: any = null
let resizeObserver: ResizeObserver | null = null

function buildNodeData(payload: MindmapData) {
  timestampById.clear()
  // Root has no own timestamp in the LLM contract — root represents the
  // whole video, so clicking it is a no-op (no map entry).
  return {
    id: 'mm-root',
    topic: payload.root || '视频思维导图',
    children: payload.children.map((ch: MindmapNode, ci: number) => {
      const chId = `mm-ch-${ci}`
      timestampById.set(chId, ch.timestamp)
      return {
        id: chId,
        topic: ch.title,
        children: ch.children.map((leaf: MindmapNode, li: number) => {
          const leafId = `mm-leaf-${ci}-${li}`
          // Leaves inherit the parent chapter's timestamp (per plan).
          timestampById.set(leafId, leaf.timestamp)
          return {
            id: leafId,
            topic: leaf.title,
          }
        }),
      }
    }),
  }
}

async function mount() {
  if (!props.data) return
  if (!container.value) {
    // Should not happen — onMounted only runs client-side and there's
    // no <ClientOnly> wrapper. Surface this loudly because it would
    // silently leave the user with an empty rectangle.
    // eslint-disable-next-line no-console
    console.warn('[MindMap] mount aborted: container ref is null')
    return
  }
  // Dynamic import keeps the bundle out of the SSR build.
  const [{ default: MindElixir }] = await Promise.all([
    import('mind-elixir'),
    import('mind-elixir/style.css'),
  ])

  // Tear down a previous instance before mounting a new one (re-mount
  // happens when `data` changes — e.g. switching videos).
  await teardown()

  // If the container is 0×0 (parent uses display:none — e.g. the user
  // hasn't switched to the mindmap tab yet), Mind-Elixir lays everything
  // out at (0, 0) and the user sees an empty rectangle. Defer init until
  // the container is visible.
  if (!container.value.clientWidth || !container.value.clientHeight) {
    // Try again on the next animation frame — the parent's display:none
    // → block toggle on tab switch fires layout synchronously.
    requestAnimationFrame(() => mount())
    return
  }

  me = new MindElixir({
    el: container.value,
    direction: 2, // SIDE — chapters radiate left & right from root
    editable: false,
    contextMenu: false,
    toolBar: true,
    keypress: false,
    // Dark theme matching the host UI (dark-bg #0a0a0f, primary gradient
    // #ff6b6b → #feca57). Use the gradient endpoints for branch colors.
    theme: {
      name: 'VidSumAIDark',
      type: 'dark',
      palette: ['#ff6b6b', '#feca57', '#48dbfb', '#ff9ff3', '#1dd1a1', '#5f27cd'],
      cssVar: {
        '--main-color': '#ffffff',
        '--main-bgcolor': '#1a1a24',
        '--color': '#d4d4d4',
        '--bgcolor': '#0a0a0f',
        '--root-color': '#0a0a0f',
        '--root-bgcolor': '#feca57',
        '--root-border-color': '#ff6b6b',
        '--main-radius': '10px',
        '--panel-color': '255, 255, 255',
        '--panel-bgcolor': '26, 26, 36',
        '--panel-border-color': '51, 51, 70',
      },
    },
  })
  const initErr = me.init({ nodeData: buildNodeData(props.data) })
  if (initErr) {
    // eslint-disable-next-line no-console
    console.error('[MindMap] init returned error:', initErr)
  }
  // Read-only — the mindmap is a visualization, not an editor.
  me.disableEdit()
  // Center the root node after init so the user sees the map immediately.
  try {
    me.toCenter?.()
  } catch {
    /* noop */
  }

  // Surface node clicks to the parent so it can seek the video. The
  // 'selectNodes' event fires on single-click; we take the first node.
  me.bus.addListener('selectNodes', (nodes: any[]) => {
    const node = nodes?.[0]
    if (!node || !node.id) return
    const ts = timestampById.get(node.id)
    if (ts !== undefined) emit('node-click', ts)
  })

  // Refresh layout when the panel resizes (tab switching, window resize).
  if (typeof ResizeObserver !== 'undefined' && container.value) {
    resizeObserver = new ResizeObserver(() => {
      try {
        me?.refresh?.()
        me?.toCenter?.()
      } catch {
        // mind-elixir's refresh sometimes throws during unmount — ignore.
      }
    })
    resizeObserver.observe(container.value)
  }
}

async function teardown() {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (me) {
    try {
      // mind-elixir exposes `destroy` from v5; guard for older versions.
      me.destroy?.()
    } catch {
      /* noop */
    }
    me = null
  }
  // Clear DOM left behind by mind-elixir so a remount starts clean.
  if (container.value) container.value.innerHTML = ''
}

onMounted(() => {
  if (props.data) mount()
})

// Re-mount whenever the upstream mindmap changes (new video, cache hit,
// or stream completion).
watch(
  () => props.data,
  (next, prev) => {
    if (next && next !== prev) mount()
  },
)

onBeforeUnmount(() => {
  teardown()
})
</script>

<style scoped>
/* mind-elixir's stylesheet sizes the SVG to fill its container; we just
   need to clip overflow and round corners. */
.mindmap-canvas {
  position: relative;
}
.mindmap-canvas :deep(me-root) {
  /* When the root tile is too narrow the topic text wraps oddly; widen
     it so the video title-style root reads well. */
  min-width: 120px;
}
</style>
