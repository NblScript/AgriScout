<script setup lang="ts">
/** 巡检回放的播放条：上一个 / 播放暂停 / 下一个 + 拖动条；大田按采样点、大棚按株播放。父组件手动选中时调 stop()。 */
import { onBeforeUnmount, ref } from 'vue'
import { CaretLeft, CaretRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{ count: number; label: string; interval?: number }>(), { interval: 200 })
const index = defineModel<number>({ required: true })

const playing = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

function stop() {
  playing.value = false
  if (timer) clearInterval(timer)
  timer = null
}
function toggle() {
  if (!props.count) return
  if (playing.value) return stop()
  playing.value = true
  if (index.value >= props.count - 1) index.value = 0
  timer = setInterval(() => {
    if (index.value < props.count - 1) index.value += 1
    else stop()
  }, props.interval)
}
function step(delta: number) {
  stop()
  const next = index.value + delta
  if (next >= 0 && next < props.count) index.value = next
}
onBeforeUnmount(stop)
defineExpose({ stop })
</script>

<template>
  <div class="player">
    <el-button :icon="CaretLeft" :disabled="!count || index <= 0" aria-label="上一个" @click="step(-1)" />
    <el-button type="primary" :icon="playing ? VideoPause : VideoPlay" :disabled="!count" @click="toggle">
      {{ playing ? '暂停' : '播放' }}
    </el-button>
    <el-button :icon="CaretRight" :disabled="!count || index >= count - 1" aria-label="下一个" @click="step(1)" />
    <el-slider v-model="index" :min="0" :max="Math.max(count - 1, 0)" :disabled="count < 2" :show-tooltip="false"
               class="slider" />
    <span class="label">{{ label }}</span>
  </div>
</template>

<style scoped>
.player { display: flex; align-items: center; gap: var(--space-1); }
.player :deep(.el-button + .el-button) { margin-left: 0; }
.slider { flex: 1; min-width: 80px; margin: 0 var(--space-3); }
.label { min-width: 96px; text-align: right; font-size: var(--fs-13); color: var(--text-secondary); font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
