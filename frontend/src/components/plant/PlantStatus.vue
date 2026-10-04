<script setup lang="ts">
/**
 * 一株的当前状态（D18：人工结论优先，只有模型结果时是占位分数）：状态、依据、可信度、
 * 最近一张合格叶背的时间（确认挂在它上面）、最近拍到的时间。单株时间线、待确认面板共用。
 */
import { computed } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import StateTag from '../ui/StateTag.vue'
import { PLANT_SOURCE_LABELS, type PlantState } from '../../types'
import { fieldClock, relativeTime } from '../../utils/fieldTime'

const props = withDefaults(defineProps<{ state: PlantState | null; loaded?: boolean; now?: number }>(), {
  loaded: true,
  now: () => Date.now(),
})

const basis = computed(() => {
  const s = props.state
  if (!s) return ''
  if (s.source === 'human') return s.reviewed_at ? `${PLANT_SOURCE_LABELS.human} · ${fieldClock(s.reviewed_at)}` : PLANT_SOURCE_LABELS.human
  if (s.source === 'model') return `${PLANT_SOURCE_LABELS.model}，分数 ${s.model_score?.toFixed(2) ?? '—'}，不是诊断`
  return PLANT_SOURCE_LABELS.none
})
</script>

<template>
  <div v-if="state" class="status">
    <div class="state-line">
      <StateTag :state="state.state" />
      <span class="basis">{{ basis }}</span>
    </div>
    <dl class="facts">
      <div>
        <dt>可信度</dt>
        <dd class="num">{{ state.confidence.toFixed(1) }}</dd>
      </div>
      <div>
        <dt>最近合格叶背</dt>
        <dd>
          <template v-if="state.last_under_ok_at">
            <span class="num">{{ fieldClock(state.last_under_ok_at) }}</span>
            <span class="muted text-12">{{ relativeTime(state.last_under_ok_at, now) }}</span>
          </template>
          <span v-else class="muted">还没有</span>
        </dd>
      </div>
      <div>
        <dt>最近拍到</dt>
        <dd>
          <span v-if="state.last_seen_at" class="num">{{ fieldClock(state.last_seen_at) }}</span>
          <span v-else class="muted">还没有</span>
        </dd>
      </div>
    </dl>
    <p v-if="state.last_under_accepted === false" class="warn">
      <el-icon><WarningFilled /></el-icon>最近一张叶背不合格，计划会排补拍
    </p>
  </div>
  <el-skeleton v-else-if="!loaded" animated :rows="3" />
  <p v-else class="muted text-13 none">拿不到这株的当前状态（可能已停用），照片和确认不受影响</p>
</template>

<style scoped>
.status { display: flex; flex-direction: column; gap: var(--space-3); }
.state-line { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.basis { font-size: var(--fs-13); color: var(--text-secondary); }
.facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); margin: 0; }
.facts div { min-width: 0; }
dt { font-size: var(--fs-12); line-height: var(--lh-12); color: var(--text-secondary); }
dd { display: flex; flex-direction: column; margin: 2px 0 0; font-size: var(--fs-14); line-height: var(--lh-14); color: var(--text-primary); }
.num { font-variant-numeric: tabular-nums; }
.warn { display: flex; align-items: center; gap: var(--space-1); margin: 0; font-size: var(--fs-13); color: var(--warning-ink); }
.none { margin: 0; }

@media (max-width: 479px) {
  .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
