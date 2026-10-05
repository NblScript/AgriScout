<script setup lang="ts">
/**
 * 大田模式的采样点卡（小麦方法验证资产，D16 保留）：照片与病斑框、生育期、长势、绿色覆盖、风险分、检出、人工复核、沿线环境曲线。
 * 与改版前的回放详情卡内容一致，只换样式。
 */
import { computed } from 'vue'
import type { EChartsOption } from 'echarts'
import EChart from '../EChart.vue'
import PatrolDetections from './PatrolDetections.vue'
import PatrolPointPhoto from './PatrolPointPhoto.vue'
import PointReviewBox from './PointReviewBox.vue'
import { VIGOR_COLORS, type CapturePointFull } from '../../types'
import { fieldClock } from '../../utils/fieldTime'

const props = defineProps<{ points: CapturePointFull[]; index: number }>()
const emit = defineEmits<{ annotated: [] }>()

const point = computed(() => props.points[props.index] ?? null)
const analysis = computed(() => point.value?.analysis ?? null)
const stageName = computed(() => (analysis.value?.growth_stage?.name as string | undefined) ?? null)
const risk = computed(() => (analysis.value?.risk_score == null ? 0 : Math.round(analysis.value.risk_score * 100)))

function vigorStars(level: number | null): string {
  if (!level) return '—'
  return '★★★★★'.slice(0, level) + '☆☆☆☆☆'.slice(0, 5 - level)
}
/** 绿色覆盖率（detail.green_ratio）不饱和，比 NDVI 代理更能区分长势；旧数据没有该字段时退回代理值。 */
const greenCover = computed(() => {
  const a = analysis.value
  if (!a) return '—'
  const ratio = a.detail?.green_ratio
  if (typeof ratio === 'number') return `${Math.round(ratio * 100)}%`
  return a.ndvi != null ? `NDVI代理 ${a.ndvi}` : '—'
})

/* ---------- 沿线天气曲线（图表配色走令牌） ---------- */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
const weatherOption = computed<EChartsOption>(() => {
  const pts = props.points
  const axis = {
    axisLine: { lineStyle: { color: token('--chart-grid') } },
    axisLabel: { color: token('--chart-axis'), fontSize: 10 },
    splitLine: { lineStyle: { color: token('--chart-grid') } },
  }
  const warm = token('--chart-warm')
  const wet = token('--chart-wet')
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['气温', '土湿'], top: 0, right: 0, textStyle: { color: token('--chart-axis'), fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 34, right: 36, top: 24, bottom: 20 },
    xAxis: { type: 'category', boundaryGap: false, ...axis, data: pts.map((p) => `${p.distance_m.toFixed(1)}m`) },
    yAxis: [{ type: 'value', ...axis }, { type: 'value', ...axis, splitLine: { show: false } }],
    series: [
      {
        name: '气温', type: 'line', smooth: true, showSymbol: false, sampling: 'lttb',
        lineStyle: { color: warm, width: 1.5 }, itemStyle: { color: warm },
        data: pts.map((p) => p.weather?.temp_c ?? null),
        markLine: props.index < pts.length
          ? { symbol: 'none', label: { show: false }, lineStyle: { color: token('--brand-600'), width: 1 }, data: [{ xAxis: props.index }] }
          : undefined,
      },
      {
        name: '土湿', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, sampling: 'lttb',
        lineStyle: { color: wet, width: 1.5 }, itemStyle: { color: wet },
        data: pts.map((p) => p.weather?.soil_moisture_pct ?? null),
      },
    ],
  }
})
</script>

<template>
  <div v-if="point" class="point-card">
    <header class="head">
      <h4>采样点 #{{ point.seq }}</h4>
      <span class="muted text-12">里程 {{ point.distance_m }} m · {{ fieldClock(point.captured_at) }}</span>
    </header>
    <PatrolPointPhoto :point="point" :max-height="200" />

    <dl v-if="analysis" class="kv">
      <div><dt>生育期</dt><dd>{{ stageName ?? '—' }}</dd></div>
      <div>
        <dt>长势等级</dt>
        <dd class="stars" :style="{ color: VIGOR_COLORS[analysis.vigor_level ?? 0] || 'var(--text-secondary)' }">
          {{ vigorStars(analysis.vigor_level) }}<span v-if="analysis.vigor_level" class="sr"> {{ analysis.vigor_level }} 级</span>
        </dd>
      </div>
      <div>
        <dt>绿色覆盖</dt>
        <dd :title="`NDVI 代理值 ${analysis.ndvi ?? '—'}（由绿色占比线性近似，覆盖率约 60% 以上即饱和为 1）`">{{ greenCover }}</dd>
      </div>
      <div class="risk">
        <dt>风险分</dt>
        <dd>
          <el-progress :percentage="risk" :color="risk > 60 ? 'var(--danger)' : 'var(--brand-600)'" :stroke-width="10" />
        </dd>
      </div>
    </dl>
    <p v-else class="muted text-13 none">这个点没有分析结果</p>
    <PatrolDetections :detections="analysis?.disease_detections ?? []" />

    <el-divider />
    <PointReviewBox :point-id="point.id" @changed="emit('annotated')" />
    <el-divider />
    <h5 class="chart-title">沿线环境曲线 <span class="muted">绿线为当前点</span></h5>
    <EChart :option="weatherOption" class="chart" />
  </div>
  <p v-else class="muted text-13">这次巡检没有采样点</p>
</template>

<style scoped>
.point-card { display: flex; flex-direction: column; gap: var(--space-3); }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-2); flex-wrap: wrap; }
.head h4 { margin: 0; font-size: var(--fs-14); font-weight: var(--fw-semibold); }
.kv { display: flex; flex-direction: column; gap: var(--space-2); margin: 0; }
.kv > div { display: flex; align-items: center; gap: var(--space-3); }
.kv dt { flex: none; width: 64px; font-size: var(--fs-13); color: var(--text-secondary); }
.kv dd { flex: 1; margin: 0; font-size: var(--fs-14); font-weight: var(--fw-medium); color: var(--text-primary); }
.stars { letter-spacing: 1px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.none { margin: 0; }
.point-card :deep(.el-divider) { margin: var(--space-1) 0; }
.chart-title { margin: 0; font-size: var(--fs-13); font-weight: var(--fw-semibold); }
.chart-title .muted { font-weight: var(--fw-regular); font-size: var(--fs-12); margin-left: var(--space-1); }
.chart { height: 150px; }
</style>
