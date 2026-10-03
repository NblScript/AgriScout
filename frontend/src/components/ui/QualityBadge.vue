<script setup lang="ts">
/**
 * 图像质量徽标（iq-rule-v1）：合格 / 不合格（写原因）/ 未测。
 * 口径与后端一致：车端 accepted 优先，没有再看质量结果的 ok（计划 0015）。
 */
import { computed } from 'vue'
import { CircleCheckFilled, QuestionFilled, WarningFilled } from '@element-plus/icons-vue'
import { QUALITY_REASON_LABELS, type ImageQuality } from '../../types'

const props = withDefaults(defineProps<{ quality?: ImageQuality | null; accepted?: boolean | null; compact?: boolean }>(), {
  quality: null,
  accepted: null,
  compact: false,
})

const ok = computed<boolean | null>(() => {
  if (typeof props.accepted === 'boolean') return props.accepted
  return typeof props.quality?.ok === 'boolean' ? props.quality.ok : null
})
const reasons = computed(() => (props.quality?.reasons ?? []).map((r) => QUALITY_REASON_LABELS[r] ?? r))
const text = computed(() => {
  if (ok.value === true) return '合格'
  if (ok.value === false) return props.compact || !reasons.value.length ? '不合格' : `不合格 · ${reasons.value.join('、')}`
  return '未测'
})
const detail = computed(() => {
  const q = props.quality
  if (!q) return ok.value == null ? '没有质量记录' : '车端判定，无明细'
  const fmt = (v: number | null | undefined, digits = 2) => (v == null ? '—' : v.toFixed(digits))
  return [
    `方法 ${q.method}`,
    `清晰度 ${fmt(q.sharpness, 1)}`,
    `平均亮度 ${fmt(q.mean_luma, 1)}`,
    `过曝 ${fmt(q.clip_high, 3)} / 欠曝 ${fmt(q.clip_low, 3)}`,
    `逆光 ${q.backlit == null ? '—' : q.backlit ? '是' : '否'}`,
    reasons.value.length ? `原因：${reasons.value.join('、')}` : '',
  ].filter(Boolean).join('\n')
})
</script>

<template>
  <el-tooltip placement="top" :show-after="200">
    <template #content><span class="qb-detail">{{ detail }}</span></template>
    <span class="quality-badge" :class="ok === true ? 'is-ok' : ok === false ? 'is-bad' : 'is-unknown'">
      <el-icon :size="13">
        <CircleCheckFilled v-if="ok === true" />
        <WarningFilled v-else-if="ok === false" />
        <QuestionFilled v-else />
      </el-icon>
      {{ text }}
    </span>
  </el-tooltip>
</template>

<style scoped>
.quality-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-12);
  line-height: 1;
  white-space: nowrap;
}
.is-ok { color: var(--success-ink); background: var(--success-soft); }
.is-bad { color: var(--danger-ink); background: var(--danger-soft); }
.is-unknown { color: var(--info-ink); background: var(--info-soft); }
.qb-detail { white-space: pre-line; font-variant-numeric: tabular-nums; }
</style>
