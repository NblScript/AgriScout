<script setup lang="ts">
/**
 * 指标卡：标签 + 数值（等宽）+ 单位 + 变化 + 说明。
 * value 为空时显示 emptyText（如「环境数据不足」），不显示成 0 或低值。
 */
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  label: string
  value?: number | string | null
  unit?: string
  precision?: number
  hint?: string
  /** 与上一期相比的变化量；invertDelta 表示「升高是坏事」（如风险） */
  delta?: number | null
  deltaLabel?: string
  invertDelta?: boolean
  emptyText?: string
  tone?: 'default' | 'success' | 'warning' | 'danger'
  loading?: boolean
  /** 一行放五六张时用：内边距、数值字号小一档 */
  compact?: boolean
}>(), {
  value: null,
  unit: undefined,
  precision: undefined,
  hint: undefined,
  delta: null,
  deltaLabel: '',
  invertDelta: false,
  emptyText: '—',
  tone: 'default',
  loading: false,
  compact: false,
})

const empty = computed(() => props.value == null || props.value === '')
const display = computed(() => {
  if (empty.value) return props.emptyText
  if (typeof props.value === 'number' && props.precision != null) return props.value.toFixed(props.precision)
  return String(props.value)
})
const deltaText = computed(() => {
  const d = props.delta
  if (d == null) return ''
  if (d === 0) return '持平'
  const abs = props.precision != null ? Math.abs(d).toFixed(props.precision) : String(Math.abs(d))
  return `${d > 0 ? '↑' : '↓'} ${abs}`
})
const deltaTone = computed(() => {
  const d = props.delta
  if (d == null || d === 0) return 'flat'
  return (d > 0) !== props.invertDelta ? 'good' : 'bad'
})
</script>

<template>
  <div class="stat-card" :class="{ compact }">
    <div class="sc-label"><slot name="label">{{ label }}</slot></div>
    <el-skeleton v-if="loading" :rows="0" animated class="sc-skeleton">
      <template #template><el-skeleton-item variant="h1" style="width: 60%" /></template>
    </el-skeleton>
    <template v-else>
      <div class="sc-value-row" :class="{ 'is-empty': empty }">
        <el-icon v-if="empty && emptyText !== '—'" class="sc-empty-icon"><InfoFilled /></el-icon>
        <span class="sc-value" :class="[`tone-${tone}`]">{{ display }}</span>
        <span v-if="unit && !empty" class="sc-unit">{{ unit }}</span>
        <span v-if="deltaText && !empty" class="sc-delta" :class="`is-${deltaTone}`">
          {{ deltaText }}<template v-if="deltaLabel"> {{ deltaLabel }}</template>
        </span>
      </div>
      <div v-if="$slots.default" class="sc-extra"><slot /></div>
      <p v-if="hint || $slots.hint" class="sc-hint"><slot name="hint">{{ hint }}</slot></p>
    </template>
  </div>
</template>

<style scoped>
.stat-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-4) var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
}
.sc-label {
  font-size: var(--fs-13);
  line-height: var(--lh-13);
  color: var(--text-secondary);
}
.sc-value-row {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-2);
  min-height: var(--lh-24);
}
.sc-value {
  font-size: var(--fs-24);
  line-height: var(--lh-24);
  font-weight: var(--fw-semibold);
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
.tone-success { color: var(--success-ink); }
.tone-warning { color: var(--warning-ink); }
.tone-danger { color: var(--danger-ink); }
.is-empty { align-items: center; gap: 6px; }
.is-empty .sc-value {
  font-size: var(--fs-16);
  line-height: var(--lh-24);
  font-weight: var(--fw-medium);
  color: var(--text-secondary);
}
.sc-empty-icon { color: var(--text-placeholder); }
.sc-unit { font-size: var(--fs-13); color: var(--text-secondary); }
.sc-delta {
  font-size: var(--fs-12);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.sc-delta.is-good { color: var(--success-ink); }
.sc-delta.is-bad { color: var(--danger-ink); }
.sc-delta.is-flat { color: var(--text-secondary); }
.sc-extra { margin-top: var(--space-1); }
.sc-hint {
  margin: 0;
  font-size: var(--fs-12);
  line-height: var(--lh-12);
  color: var(--text-secondary);
}
.sc-skeleton { padding-top: 2px; }
.compact { padding: var(--space-3) var(--space-4); }
.compact .sc-value { font-size: var(--fs-20); line-height: var(--lh-20); }
.compact .sc-value-row { min-height: var(--lh-20); }
.compact .is-empty .sc-value { font-size: var(--fs-14); line-height: var(--lh-20); }
</style>
