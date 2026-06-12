import { ref } from 'vue'

/**
 * Shared playback state between VideoPreview (writer) and any consumer
 * that needs to react to playback (currently VideoSummary, for "currently
 * playing chapter" highlighting).
 *
 * Module-level refs act as a process-wide singleton: every importer sees
 * the same reactive instances. This is intentional for a single-page Vue
 * app where there's at most one video playing at a time.
 *
 * NOTE: The values are wall-clock snapshots updated by VideoPreview's
 * requestAnimationFrame loop, so they tick at ~60fps when the video is
 * playing. Consumers should treat them as best-effort current values, not
 * authoritative timeline state.
 */
export const currentTime = ref(0)
export const duration = ref(0)
export const isPlaying = ref(false)

/** Reset all state — call when a new video is parsed or playback stops. */
export function resetPlaybackState() {
  currentTime.value = 0
  duration.value = 0
  isPlaying.value = false
}
