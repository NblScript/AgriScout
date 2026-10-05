<script setup lang="ts">
/**
 * 棚内环境卡（展示屏、大棚详情概览共用）：最近一小时温湿度、环境风险（env_index）、清晨叶背窗口、近 72 小时曲线。
 * 「实时」以记录仪最近一次上传为准，副标题写明读数截至何时；env_index 为空写「环境数据不足」，不当成低风险。
 */
import { computed } from 'vue'
import { Sunrise } from '@element-plus/icons-vue'
import EChart from './EChart.vue'
import SectionCard from './ui/SectionCard.vue'
import { latestReadingAt } from '../composables/useGreenhouseBoard'
import type { EnvSummary } from '../types'
import { hourlyEnvOption } from '../utils/envChart'
import { fieldClock, relativeTime } from '../utils/fieldTime'

const props = defineProps<{ env: EnvSummary | null; now: number; fontSize?: number }>()

const readingAt = computed(() => latestReadingAt(props.env))
const lastHour = computed(() => [...(props.env?.hourly ?? [])].reverse().find((h) => !h.missing) ?? null)
const recent = computed(() => (props.env?.hourly ?? []).slice(-72))
const option = computed(() => hourlyEnvOption(recent.value, { dewpoint: false, fontSize: props.fontSize, splitNumber: 3 }))
const index = computed(() => props.env?.index ?? null)
const subtitle = computed(() =>
  readingAt.value == null ? '没有温湿度读数' : `读数截至 ${fieldClock(readingAt.value)} · ${relativeTime(readingAt.value, props.now)}`)

function fmt(value: number | null | undefined, digits = 1): string {
  return value == null ? '—' : value.toFixed(digits)
}
function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}
</script>

<template>
  <SectionCard title="棚内环境" :subtitle="subtitle" class="env-panel">
    <div class="metrics">
      <div class="metric">
        <span class="m-label">温度 <small>最近一小时</small></span>
        <span class="m-value"><b>{{ fmt(lastHour?.temp_c) }}</b><small v-if="lastHour?.temp_c != null">℃</small></span>
      </div>
      <div class="metric">
        <span class="m-label">相对湿度</span>
        <span class="m-value"><b>{{ fmt(lastHour?.humidity_pct) }}</b><small v-if="lastHour?.humidity_pct != null">%</small></span>
      </div>
      <div class="metric risk">
        <span class="m-label">环境风险 <small>近 72 小时</small></span>
        <template v-if="index?.env_index != null">
          <span class="m-value"><b>{{ index.env_index.toFixed(2) }}</b></span>
          <span class="meter" aria-hidden="true"><i :style="{ width: `${index.env_index * 100}%` }" /></span>
        </template>
        <span v-else class="m-missing" :title="index?.reason ?? ''">环境数据不足</span>
      </div>
    </div>

    <p class="line">
      <template v-if="index">
        适宜 {{ index.favorable_hours }} 小时 · 湿润 {{ index.wet_hours }} 小时 · 读数覆盖 {{ pct(index.coverage) }}
        <template v-if="index.env_index == null && index.reason">（{{ index.reason }}）</template>
      </template>
      <template v-else>没有拿到环境数据</template>
    </p>
    <p class="window" :class="{ on: env?.morning_window }">
      <el-icon><Sunrise /></el-icon>
      <template v-if="env?.morning_window">
        清晨叶背窗口 {{ env.morning_window.start }}–{{ env.morning_window.end }}（前夜湿润 {{ env.morning_window.night_wet_hours }} 小时）
      </template>
      <template v-else>今天没有清晨叶背窗口</template>
    </p>

    <div v-if="readingAt != null" class="chart"><EChart :option="option" /></div>
    <p v-else class="none">这个棚还没有温湿度记录仪的读数。记录仪数据上传后，这里显示最近一小时的温湿度和近 72 小时曲线。</p>
  </SectionCard>
</template>

<style scoped>
.env-panel { display: flex; flex-direction: column; }
.env-panel :deep(.sc-body) { flex: 1; display: flex; flex-direction: column; gap: var(--space-2); min-height: 0; }
.metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.metric { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.m-label { font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-secondary); white-space: nowrap; }
.m-label small { font-size: var(--fs-12); color: var(--text-placeholder); }
.m-value { display: flex; align-items: baseline; gap: 4px; }
.m-value b {
  font-size: var(--fs-30);
  line-height: var(--lh-30);
  font-weight: var(--fw-semibold);
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
.m-value small { font-size: var(--fs-14); color: var(--text-secondary); }
.m-missing {
  align-self: flex-start;
  margin-top: 4px;
  padding: 2px var(--space-2);
  font-size: var(--fs-14);
  line-height: var(--lh-16);
  white-space: nowrap;
  font-weight: var(--fw-medium);
  color: var(--info-ink);
  border: 1px dashed var(--neutral-400);
  border-radius: var(--radius-sm);
}
.meter { height: 6px; border-radius: 3px; background: var(--neutral-200); overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--warning); border-radius: 3px; }
.line, .window { margin: 0; font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-secondary); }
.window { display: flex; align-items: center; gap: var(--space-1); }
.window.on { color: var(--warning-ink); }
/* 放在固定高度的右栏里时随剩余高度伸缩，最矮 110 */
.chart { flex: 1 1 170px; min-height: 110px; margin-top: var(--space-1); }
.none { margin: var(--space-3) 0 0; padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--bg-subtle); font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-secondary); }
</style>
