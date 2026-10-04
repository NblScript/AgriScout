<script setup lang="ts">
/**
 * 大棚详情 · 环境（0015 的环境曲线）：近 7 天逐时温湿度、露点差，按田间日期汇总的适宜 / 湿润 / 夜间湿润时长；
 * 环境风险只看最近 72 小时，读数覆盖不够时写「环境数据不足」，不当成低风险。
 */
import { computed, onMounted } from 'vue'
import type { EChartsOption } from 'echarts'
import EChart from '../../components/EChart.vue'
import EmptyState from '../../components/ui/EmptyState.vue'
import SectionCard from '../../components/ui/SectionCard.vue'
import StatCard from '../../components/ui/StatCard.vue'
import { latestReadingAt } from '../../composables/useGreenhouseBoard'
import { useFieldDetail } from '../../composables/useFieldDetail'
import { cssVar } from '../../styles/tokens'
import { chartBase, hourlyEnvOption } from '../../utils/envChart'
import { fieldClock, relativeTime } from '../../utils/fieldTime'

const d = useFieldDetail()
onMounted(() => { void d.env.load() })

const env = computed(() => d.env.data.value)
const readingAt = computed(() => latestReadingAt(env.value))
const hasReadings = computed(() => !!env.value && env.value.hourly.some((h) => !h.missing))

function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

const hourlyOption = computed<EChartsOption>(() => hourlyEnvOption(env.value?.hourly ?? []))

const dailyOption = computed<EChartsOption>(() => {
  const days = env.value?.daily ?? []
  const base = chartBase()
  return {
    textStyle: base.textStyle,
    tooltip: {
      trigger: 'axis',
      // 当天读数不全时（比如今天才过了几个小时）一并写出覆盖率，免得把半天的数当成一整天
      formatter: (params: unknown) => {
        const rows = params as { dataIndex: number; marker: string; seriesName: string; value: number }[]
        const day = days[rows[0]?.dataIndex ?? 0]
        if (!day) return ''
        const lines = rows.map((r) => `${r.marker}${r.seriesName} ${r.value} 小时`)
        return [`${day.field_date}（读数覆盖 ${pct(day.coverage)}）`, ...lines].join('<br/>')
      },
    },
    legend: { ...base.legend, data: ['适宜时长', '湿润时长', '夜间湿润'] },
    grid: { left: 36, right: 12, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: days.map((day) => day.field_date.slice(5)), axisLine: base.axisLine, axisTick: { show: false }, axisLabel: base.axisLabel },
    yAxis: { type: 'value', name: '小时', max: 24, nameTextStyle: base.axisLabel, axisLabel: base.axisLabel, splitLine: base.splitLine },
    series: [
      { name: '适宜时长', type: 'bar', barMaxWidth: 14, data: days.map((day) => day.favorable_hours), color: cssVar('--chart-warm', '#c8691f') },
      { name: '湿润时长', type: 'bar', barMaxWidth: 14, data: days.map((day) => day.wet_hours), color: cssVar('--chart-wet', '#2f6fb0') },
      { name: '夜间湿润', type: 'bar', barMaxWidth: 14, data: days.map((day) => day.night_wet_hours), color: cssVar('--chart-night', '#1f8a83') },
    ],
  }
})
</script>

<template>
  <div class="kpis">
    <StatCard compact label="环境风险 · 近 72 小时" :value="env?.index.env_index ?? null" :precision="2" :loading="!d.env.loaded.value"
              :empty-text="env ? '环境数据不足' : '—'"
              :hint="env?.index.env_index == null && env?.index.reason ? env.index.reason : 'dm-env-v0，越高越利于霜霉病'" />
    <StatCard compact label="适宜 / 湿润时长" :value="env ? `${env.index.favorable_hours} / ${env.index.wet_hours}` : null" unit="小时"
              :loading="!d.env.loaded.value" hint="近 72 小时" />
    <StatCard compact label="读数覆盖" :value="env ? pct(env.index.coverage) : null" :loading="!d.env.loaded.value"
              hint="低于 50% 时不算环境风险" />
    <StatCard compact label="清晨叶背窗口" :value="env?.morning_window ? `${env.morning_window.start}–${env.morning_window.end}` : null"
              :empty-text="env ? '今天没有' : '—'" :loading="!d.env.loaded.value"
              :hint="env?.morning_window ? `前夜湿润 ${env.morning_window.night_wet_hours} 小时` : '前夜湿润不足 4 小时'" />
    <StatCard compact label="读数截至" :value="readingAt != null ? fieldClock(readingAt) : null" empty-text="没有读数"
              :loading="!d.env.loaded.value"
              :hint="readingAt != null ? `${relativeTime(readingAt)} · 记录仪 ${env?.sensors.join('、')}` : '记录仪数据还没上传'" />
  </div>

  <SectionCard title="棚内环境" subtitle="近 7 天逐时读数与按田间日期汇总的时长（缺测不插值，曲线断开）；环境风险只看最近 72 小时">
    <div v-if="hasReadings" class="charts">
      <div class="chart"><EChart :option="hourlyOption" /></div>
      <div class="chart narrow"><EChart :option="dailyOption" /></div>
    </div>
    <EmptyState v-else-if="d.env.loaded.value" compact :title="d.env.error.value || '还没有温湿度读数'"
                description="记录仪导出的 CSV 可用 rover/env_upload.py 上传；没有读数时环境风险按「环境数据不足」处理，不当成低风险。" />
    <el-skeleton v-else animated :rows="5" />
  </SectionCard>
</template>

<style scoped>
.kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-3); margin-bottom: var(--space-4); }
.charts { display: flex; gap: var(--space-4); }
.chart { flex: 2; min-width: 0; height: 300px; }
.chart.narrow { flex: 1; }
@media (max-width: 1279px) {
  .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1023px) {
  .charts { flex-direction: column; }
  .chart.narrow { height: 240px; }
}
@media (max-width: 767px) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
