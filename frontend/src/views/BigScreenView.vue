<script setup lang="ts">
/** /screen 数据总览：亮色专业工具风。中央地图 + 左右图表，数据全部来自平台真实接口。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'
import MapCanvas from '../components/MapCanvas.vue'
import ScreenPanel from '../components/ScreenPanel.vue'
import EChart from '../components/EChart.vue'
import { advicesApi, capturePointsApi, fieldsApi, patrolsApi, statsApi } from '../api'
import {
  VIGOR_COLORS,
  type Advice,
  type CapturePointFull,
  type PatrolDetail,
  type RecentPatrolStat,
  type StatsOverview,
} from '../types'

const router = useRouter()

const overview = ref<StatsOverview | null>(null)
const patrol = ref<PatrolDetail | null>(null)
const points = ref<CapturePointFull[]>([])
const advices = ref<Advice[]>([])
const fieldBoundary = ref<{ type: string; coordinates: number[][][] } | null>(null)
const selectedPatrolId = ref<number | null>(null)
const switching = ref(false)

/* ---------- 实时时钟 ---------- */
const now = ref(new Date())
let clockTimer: ReturnType<typeof setInterval> | null = null
const clock = computed(() =>
  now.value.toLocaleTimeString('zh-CN', { hour12: false }),
)
const dateStr = computed(() =>
  now.value.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'long' }),
)

/* ---------- 数据加载 ---------- */
async function loadOverview() {
  overview.value = await statsApi.overview()
  const first = overview.value.recent_patrols[0]
  if (first && selectedPatrolId.value === null) {
    await selectPatrol(first.patrol_id)
  }
}

async function selectPatrol(id: number) {
  if (switching.value) return
  switching.value = true
  selectedPatrolId.value = id
  try {
    const detail = await patrolsApi.get(id)
    patrol.value = detail
    const [pts, adv, field] = await Promise.all([
      capturePointsApi.listByPatrol(id),
      advicesApi.list(id).catch(() => ({ items: [] as Advice[] })),
      fieldsApi.get(detail.field_id).catch(() => null),
    ])
    points.value = pts.items
    advices.value = adv.items
    fieldBoundary.value = (field?.boundary as typeof fieldBoundary.value) ?? null
  } finally {
    switching.value = false
  }
}

const currentStat = computed<RecentPatrolStat | null>(() =>
  overview.value?.recent_patrols.find((r) => r.patrol_id === selectedPatrolId.value) ?? null,
)

onMounted(async () => {
  clockTimer = setInterval(() => { now.value = new Date() }, 1000)
  try {
    await loadOverview()
  } catch { /* 后端未就绪时总览保持空态，不崩溃 */ }
})
onBeforeUnmount(() => { if (clockTimer) clearInterval(clockTimer) })

/* ---------- 图表：亮色统一色板 ---------- */
const C = {
  green: '#16a34a',
  blue: '#2563eb',
  amber: '#d97706',
  red: '#dc2626',
  text: '#7a8a7e',
  axisLine: '#d7dfd8',
  splitLine: '#edf1ed',
}
const AXIS = {
  axisLine: { lineStyle: { color: C.axisLine } },
  axisLabel: { color: C.text, fontSize: 10 },
  splitLine: { lineStyle: { color: C.splitLine } },
}

const kpis = computed(() => {
  const o = overview.value
  return [
    { label: '地块', value: o?.fields ?? '—' },
    { label: '作物', value: o?.crops ?? '—' },
    { label: '种植批次', value: o?.plantings ?? '—' },
    { label: '设备', value: o?.devices ?? '—' },
    { label: '巡检任务', value: o?.patrols ?? '—' },
    { label: '采样点', value: o?.capture_points ?? '—' },
    { label: '已分析点', value: o?.analyzed_points ?? '—' },
    { label: '人工标注', value: o?.annotations ?? '—' },
  ]
})

const acceptRate = computed(() => {
  const o = overview.value
  if (!o || o.advices_total === 0) return '—'
  return `${Math.round((o.advices_accepted / o.advices_total) * 100)}%`
})

const adviceRingOption = computed<EChartsOption>(() => {
  const o = overview.value
  return {
    tooltip: { trigger: 'item' },
    title: {
      text: `${acceptRate.value}`,
      subtext: '采纳率',
      left: 'center', top: '36%',
      textStyle: { color: '#1f2d1f', fontSize: 20, fontWeight: 600 },
      subtextStyle: { color: C.text, fontSize: 11 },
    },
    series: [{
      type: 'pie', radius: ['58%', '80%'],
      label: { show: false },
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      data: [
        { value: o?.advices_accepted ?? 0, name: '已采纳', itemStyle: { color: C.green } },
        { value: o?.advices_suggested ?? 0, name: '待处理', itemStyle: { color: C.amber } },
        { value: o?.advices_rejected ?? 0, name: '已驳回', itemStyle: { color: C.red } },
      ],
    }],
  }
})

const trendOption = computed<EChartsOption>(() => {
  const list = [...(overview.value?.recent_patrols ?? [])].reverse()
  return {
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['采样点数', '平均NDVI'], top: 0, right: 0,
      textStyle: { color: C.text, fontSize: 10 }, itemWidth: 14, itemHeight: 8,
    },
    grid: { left: 40, right: 34, top: 26, bottom: 22 },
    xAxis: { type: 'category', data: list.map((r) => `#${r.patrol_id}`), ...AXIS },
    yAxis: [
      { type: 'value', ...AXIS },
      { type: 'value', max: 1, ...AXIS, splitLine: { show: false } },
    ],
    series: [
      {
        name: '采样点数', type: 'bar', barWidth: 14,
        itemStyle: { borderRadius: [3, 3, 0, 0], color: C.green },
        data: list.map((r) => r.point_count),
      },
      {
        name: '平均NDVI', type: 'line', smooth: true, yAxisIndex: 1,
        lineStyle: { color: C.blue, width: 2 }, itemStyle: { color: C.blue },
        symbolSize: 5, data: list.map((r) => r.avg_ndvi),
      },
    ],
  }
})

const vigorOption = computed<EChartsOption>(() => {
  const dist = currentStat.value?.vigor_distribution ?? {}
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 26, right: 8, top: 16, bottom: 20 },
    xAxis: { type: 'category', data: ['1', '2', '3', '4', '5'], ...AXIS },
    yAxis: { type: 'value', ...AXIS },
    series: [{
      type: 'bar', barWidth: 12,
      data: ['1', '2', '3', '4', '5'].map((lv) => ({
        value: dist[lv] ?? 0,
        itemStyle: { color: VIGOR_COLORS[Number(lv)], borderRadius: [2, 2, 0, 0] },
      })),
    }],
  }
})

const riskGaugeOption = computed<EChartsOption>(() => {
  const risk = currentStat.value?.avg_risk_score ?? 0
  const pctv = Math.round(risk * 100)
  return {
    series: [{
      type: 'gauge', radius: '95%', center: ['50%', '58%'],
      startAngle: 210, endAngle: -30, min: 0, max: 100,
      progress: {
        show: true, width: 8,
        itemStyle: { color: pctv > 60 ? C.red : pctv > 30 ? C.amber : C.green },
      },
      axisLine: { lineStyle: { width: 8, color: [[1, '#edf1ed']] } },
      axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { show: false }, pointer: { show: false },
      title: { show: true, offsetCenter: [0, '38%'], color: C.text, fontSize: 11 },
      detail: {
        valueAnimation: true, offsetCenter: [0, '2%'],
        formatter: `${pctv}`, color: '#1f2d1f', fontSize: 22, fontWeight: 600,
      },
      data: [{ value: pctv, name: '平均风险分' }],
    }],
  }
})

const weatherOption = computed<EChartsOption>(() => {
  const pts = points.value
  const has = pts.some((p) => p.weather)
  const xLabels = pts.map((p) => `${p.distance_m.toFixed(1)}m`)
  return {
    tooltip: { trigger: 'axis' },
    legend: {
      data: has ? ['气温', '土壤湿度'] : [], top: 0, right: 0,
      textStyle: { color: C.text, fontSize: 10 }, itemWidth: 14, itemHeight: 8,
    },
    grid: { left: 36, right: 40, top: 26, bottom: 22 },
    xAxis: { type: 'category', data: xLabels, boundaryGap: false, ...AXIS },
    yAxis: [
      { type: 'value', ...AXIS, name: '℃', nameTextStyle: { color: C.text } },
      { type: 'value', ...AXIS, name: '%', nameTextStyle: { color: C.text }, splitLine: { show: false } },
    ],
    series: [
      {
        name: '气温', type: 'line', smooth: true, showSymbol: false, sampling: 'lttb',
        lineStyle: { color: C.amber, width: 1.6 },
        areaStyle: { color: 'rgba(217,119,6,0.07)' },
        data: pts.map((p) => p.weather?.temp_c ?? null),
      },
      {
        name: '土壤湿度', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, sampling: 'lttb',
        lineStyle: { color: C.blue, width: 1.6 },
        areaStyle: { color: 'rgba(37,99,235,0.07)' },
        data: pts.map((p) => p.weather?.soil_moisture_pct ?? null),
      },
    ],
  }
})

/* ---------- 建议信息流 ---------- */
const PRIORITY_ORDER: Record<string, number> = { high: 3, medium: 2, low: 1 }
const seqByPointId = computed(() => new Map(points.value.map((p) => [p.id, p.seq])))
const adviceFeed = computed(() =>
  [...advices.value]
    .sort((a, b) =>
      (PRIORITY_ORDER[b.priority] ?? 0) - (PRIORITY_ORDER[a.priority] ?? 0)
      || b.created_at.localeCompare(a.created_at))
    .slice(0, 8),
)

const analysisStatusLabel: Record<string, string> = {
  pending: '待分析', running: '分析中', done: '分析完成', error: '分析失败',
}
</script>

<template>
  <div class="overview">
    <!-- 顶栏 -->
    <header class="ov-head-bar">
      <div class="clock-box">
        <b class="num">{{ clock }}</b>
        <span>{{ dateStr }}</span>
      </div>
      <div class="title-text">
        <h1>农田巡检数据总览</h1>
      </div>
      <div class="head-right">
        <button class="ghost-btn" @click="router.push('/dashboard')">进入工作台 →</button>
      </div>
    </header>

    <!-- 三栏主体 -->
    <main class="ov-main">
      <!-- 左列 -->
      <div class="col">
        <ScreenPanel title="平台资源" class="p-resource">
          <div class="kpi-grid">
            <div v-for="k in kpis" :key="k.label" class="kpi">
              <b class="num">{{ k.value }}</b><span>{{ k.label }}</span>
            </div>
          </div>
        </ScreenPanel>
        <ScreenPanel title="农事建议处理" :subtitle="`累计 ${overview?.advices_total ?? 0} 条`" class="p-ring">
          <EChart :option="adviceRingOption" />
        </ScreenPanel>
        <ScreenPanel title="巡检趋势" subtitle="近 5 次" class="p-trend">
          <EChart :option="trendOption" />
        </ScreenPanel>
      </div>

      <!-- 中央地图 -->
      <div class="col center">
        <ScreenPanel title="巡检地图" subtitle="选择巡检查看轨迹与长势" class="p-map">
          <div class="map-toolbar">
            <button
              v-for="r in overview?.recent_patrols ?? []" :key="r.patrol_id"
              class="chip" :class="{ active: r.patrol_id === selectedPatrolId }"
              @click="selectPatrol(r.patrol_id)"
            >
              巡检 #{{ r.patrol_id }} · {{ r.field_name ?? '未命名地块' }}
            </button>
            <span v-if="!overview?.recent_patrols.length" class="empty-tip">暂无巡检数据——先运行模拟器生成</span>
          </div>
          <div class="map-wrap">
            <MapCanvas
              theme="light"
              :boundary="fieldBoundary"
              :track="patrol?.track ?? null"
              :points="points"
              :selected-index="null"
            />
          </div>
          <div class="map-strip" v-if="patrol">
            <span>巡检 #{{ patrol.id }}</span>
            <span>{{ patrol.field_name ?? `地块#${patrol.field_id}` }}</span>
            <span>{{ patrol.device_code ?? '未知设备' }}</span>
            <span>{{ patrol.point_count }} 点</span>
            <span :class="patrol.analysis_status === 'done' ? 'ok' : 'warn'">
              {{ analysisStatusLabel[patrol.analysis_status] ?? patrol.analysis_status }}
            </span>
            <span class="strip-time">{{ new Date(patrol.started_at).toLocaleString('zh-CN', { hour12: false }) }}</span>
          </div>
        </ScreenPanel>
      </div>

      <!-- 右列 -->
      <div class="col">
        <ScreenPanel title="最新巡检分析" :subtitle="patrol ? `巡检 #${patrol.id}` : ''" class="p-analysis">
          <div class="analysis-row">
            <div class="half"><EChart :option="vigorOption" /></div>
            <div class="half"><EChart :option="riskGaugeOption" /></div>
          </div>
          <div class="analysis-caption">
            <span>长势分布（1 差 → 5 旺）</span>
            <span v-if="currentStat" class="stress">胁迫检出 {{ currentStat.stress_points }} 点</span>
          </div>
        </ScreenPanel>
        <ScreenPanel title="沿线环境" subtitle="气温 / 土壤湿度" class="p-weather">
          <EChart :option="weatherOption" />
        </ScreenPanel>
        <ScreenPanel title="最新农事建议" :subtitle="`采纳率 ${acceptRate}`" class="p-feed">
          <div class="advice-feed">
            <div v-for="a in adviceFeed" :key="a.id" class="feed-item">
              <i :class="['dot', a.priority]" />
              <div class="feed-main">
                <p class="feed-content">{{ a.content }}</p>
                <p class="feed-meta">
                  {{ a.capture_point_id != null ? `点#${seqByPointId.get(a.capture_point_id) ?? '?'}` : '全局' }}
                  · {{ a.rule_snapshot.rule_key }} v{{ a.rule_snapshot.version }}
                  <template v-if="a.rule_snapshot.source"> · {{ a.rule_snapshot.source }}</template>
                </p>
              </div>
            </div>
            <p v-if="!adviceFeed.length" class="empty-tip">暂无建议——完成一次巡检分析后自动生成</p>
          </div>
        </ScreenPanel>
      </div>
    </main>
  </div>
</template>

<style scoped>
.overview {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  color: #1f2d1f;
  background: #f5f7f5;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* ---------- 顶栏 ---------- */
.ov-head-bar {
  height: 60px;
  flex: 0 0 60px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  background: #fff;
  border-bottom: 1px solid #e2e8e2;
}
.clock-box { display: flex; flex-direction: column; min-width: 170px; }
.clock-box b { font-size: 20px; font-weight: 600; color: #1f2d1f; }
.clock-box span { font-size: 11px; color: #7a8a7e; }
.title-text { flex: 1; text-align: center; }
.title-text h1 {
  font-size: 19px;
  font-weight: 600;
  color: #1f2d1f;
  letter-spacing: 2px;
}
.head-right { min-width: 170px; text-align: right; }
.ghost-btn {
  background: #fff;
  border: 1px solid #d7dfd8;
  color: #4a5d4e;
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.ghost-btn:hover {
  color: var(--el-color-primary, #15803d);
  border-color: var(--el-color-primary, #15803d);
}

/* ---------- 三栏 ---------- */
.ov-main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(360px, 23.5%) 1fr minmax(360px, 23.5%);
  gap: 12px;
  padding: 12px;
}
.col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.p-resource { flex: 3; }
.p-ring { flex: 3.2; }
.p-trend { flex: 3.2; }
.p-map { flex: 1; }
.p-analysis { flex: 3; }
.p-weather { flex: 3; }
.p-feed { flex: 3.4; }

/* KPI */
.kpi-grid {
  height: 100%;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.kpi {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: #f8faf8;
  border: 1px solid #e8eee8;
  border-radius: 8px;
}
.kpi b { font-size: 20px; font-weight: 600; color: #1f2d1f; }
.kpi span { font-size: 11px; color: #7a8a7e; }

/* 地图区 */
.p-map :deep(.ov-body) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.map-toolbar {
  flex: 0 0 auto;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.chip {
  background: #fff;
  border: 1px solid #d7dfd8;
  color: #4a5d4e;
  border-radius: 14px;
  font-size: 11px;
  padding: 3px 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.chip.active {
  color: #fff;
  background: var(--el-color-primary, #15803d);
  border-color: var(--el-color-primary, #15803d);
}
.map-wrap { flex: 1; min-height: 0; border-radius: 8px; overflow: hidden; border: 1px solid #e8eee8; }
.map-strip {
  flex: 0 0 auto;
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 12px;
  color: #4a5d4e;
  background: #f8faf8;
  border: 1px solid #e8eee8;
  border-radius: 8px;
  padding: 6px 12px;
}
.map-strip .ok { color: #16a34a; font-weight: 600; }
.map-strip .warn { color: #d97706; font-weight: 600; }
.strip-time { margin-left: auto; color: #7a8a7e; }

/* 分析行 */
.analysis-row { height: calc(100% - 26px); display: flex; gap: 8px; }
.half { flex: 1; min-width: 0; }
.analysis-caption {
  height: 18px;
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #7a8a7e;
}
.analysis-caption .stress { color: #d97706; }

/* 建议信息流 */
.advice-feed { height: 100%; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.feed-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  background: #f8faf8;
  border-left: 3px solid #d7dfd8;
  border-radius: 4px;
  padding: 7px 10px;
}
.dot { flex: 0 0 6px; width: 6px; height: 6px; border-radius: 50%; margin-top: 6px; background: #16a34a; }
.dot.high { background: #dc2626; }
.dot.medium { background: #d97706; }
.feed-content {
  font-size: 12px;
  color: #1f2d1f;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.feed-meta { font-size: 10px; color: #7a8a7e; margin-top: 3px; }

.empty-tip {
  color: #9aa79a;
  font-size: 12px;
  text-align: center;
  margin: auto;
}
</style>
