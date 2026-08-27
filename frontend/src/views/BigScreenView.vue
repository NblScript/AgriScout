<script setup lang="ts">
/** /screen 指挥大屏：深色科技风 + ECharts + 暗色 Leaflet。
 *  布局参考 sc-datav 大屏构图（中央地图 + 左右图表面板），数据全部来自平台真实接口。 */
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
  } catch { /* 后端未就绪时大屏保持空态，不崩溃 */ }
})
onBeforeUnmount(() => { if (clockTimer) clearInterval(clockTimer) })

/* ---------- 图表：统一暗色底 ---------- */
const AXIS = {
  axisLine: { lineStyle: { color: 'rgba(74,222,128,0.25)' } },
  axisLabel: { color: '#86a391', fontSize: 10 },
  splitLine: { lineStyle: { color: 'rgba(74,222,128,0.08)' } },
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
      textStyle: { color: '#d1fae5', fontSize: 22, fontWeight: 700 },
      subtextStyle: { color: '#86a391', fontSize: 11 },
    },
    series: [{
      type: 'pie', radius: ['58%', '80%'],
      label: { show: false },
      itemStyle: { borderColor: '#0a180f', borderWidth: 2 },
      data: [
        { value: o?.advices_accepted ?? 0, name: '已采纳', itemStyle: { color: '#4ade80' } },
        { value: o?.advices_suggested ?? 0, name: '待处理', itemStyle: { color: '#fbbf24' } },
        { value: o?.advices_rejected ?? 0, name: '已驳回', itemStyle: { color: '#f87171' } },
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
      textStyle: { color: '#86a391', fontSize: 10 }, itemWidth: 14, itemHeight: 8,
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
        itemStyle: { borderRadius: [4, 4, 0, 0], color: '#38bdf8' },
        data: list.map((r) => r.point_count),
      },
      {
        name: '平均NDVI', type: 'line', smooth: true, yAxisIndex: 1,
        lineStyle: { color: '#4ade80', width: 2 }, itemStyle: { color: '#4ade80' },
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
        itemStyle: { color: VIGOR_COLORS[Number(lv)], borderRadius: [3, 3, 0, 0] },
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
      progress: { show: true, width: 8, itemStyle: { color: pctv > 60 ? '#f87171' : pctv > 30 ? '#fbbf24' : '#4ade80' } },
      axisLine: { lineStyle: { width: 8, color: [[1, 'rgba(74,222,128,0.12)']] } },
      axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { show: false }, pointer: { show: false },
      title: { show: true, offsetCenter: [0, '38%'], color: '#86a391', fontSize: 11 },
      detail: {
        valueAnimation: true, offsetCenter: [0, '2%'],
        formatter: `${pctv}`, color: '#d1fae5', fontSize: 24, fontWeight: 700,
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
      textStyle: { color: '#86a391', fontSize: 10 }, itemWidth: 14, itemHeight: 8,
    },
    grid: { left: 36, right: 40, top: 26, bottom: 22 },
    xAxis: { type: 'category', data: xLabels, boundaryGap: false, ...AXIS },
    yAxis: [
      { type: 'value', ...AXIS, name: '℃', nameTextStyle: { color: '#86a391' } },
      { type: 'value', ...AXIS, name: '%', nameTextStyle: { color: '#86a391' }, splitLine: { show: false } },
    ],
    series: [
      {
        name: '气温', type: 'line', smooth: true, showSymbol: false, sampling: 'lttb',
        lineStyle: { color: '#fbbf24', width: 1.6 },
        areaStyle: { color: 'rgba(251,191,36,0.10)' },
        data: pts.map((p) => p.weather?.temp_c ?? null),
      },
      {
        name: '土壤湿度', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, sampling: 'lttb',
        lineStyle: { color: '#38bdf8', width: 1.6 },
        areaStyle: { color: 'rgba(56,189,248,0.10)' },
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
  <div class="screen">
    <!-- 顶栏 -->
    <header class="scr-head">
      <div class="clock-box">
        <b>{{ clock }}</b>
        <span>{{ dateStr }}</span>
      </div>
      <div class="title-wrap">
        <i class="title-line left" />
        <div class="title-text">
          <h1>AgriScout 农田巡检指挥中心</h1>
          <p>AGRI SCOUT COMMAND CENTER</p>
        </div>
        <i class="title-line right" />
      </div>
      <div class="head-right">
        <button class="ghost-btn" @click="router.push('/dashboard')">进入工作台 →</button>
      </div>
    </header>

    <!-- 三栏主体 -->
    <main class="scr-main">
      <!-- 左列 -->
      <div class="col">
        <ScreenPanel title="平台资源总览" subtitle="OVERVIEW" class="p-resource">
          <div class="kpi-grid">
            <div v-for="k in kpis" :key="k.label" class="kpi">
              <b>{{ k.value }}</b><span>{{ k.label }}</span>
            </div>
          </div>
        </ScreenPanel>
        <ScreenPanel title="农事建议处理" subtitle="ADVICES" class="p-ring">
          <EChart :option="adviceRingOption" />
        </ScreenPanel>
        <ScreenPanel title="巡检趋势" subtitle="TREND" class="p-trend">
          <EChart :option="trendOption" />
        </ScreenPanel>
      </div>

      <!-- 中央地图 -->
      <div class="col center">
        <ScreenPanel title="实时巡检地图" subtitle="LIVE PATROL MAP" class="p-map">
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
              theme="dark"
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
        <ScreenPanel title="最新巡检分析" subtitle="ANALYSIS" class="p-analysis">
          <div class="analysis-row">
            <div class="half"><EChart :option="vigorOption" /></div>
            <div class="half"><EChart :option="riskGaugeOption" /></div>
          </div>
          <div class="analysis-caption">
            <span>长势分布（1 差 → 5 旺）</span>
            <span v-if="currentStat" class="stress">胁迫检出 {{ currentStat.stress_points }} 点</span>
          </div>
        </ScreenPanel>
        <ScreenPanel title="沿线环境曲线" subtitle="WEATHER" class="p-weather">
          <EChart :option="weatherOption" />
        </ScreenPanel>
        <ScreenPanel title="最新农事建议" subtitle="ADVICE FEED" class="p-feed">
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
.screen {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  color: #d1fae5;
  background:
    radial-gradient(ellipse 80% 55% at 50% -10%, rgba(34, 197, 94, 0.16), transparent),
    linear-gradient(rgba(74, 222, 128, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(74, 222, 128, 0.035) 1px, transparent 1px),
    linear-gradient(180deg, #07130c, #050d08);
  background-size: auto, 44px 44px, 44px 44px, auto;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* ---------- 顶栏 ---------- */
.scr-head {
  height: 64px;
  flex: 0 0 64px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  border-bottom: 1px solid rgba(74, 222, 128, 0.18);
  background: linear-gradient(180deg, rgba(16, 38, 24, 0.6), transparent);
}
.clock-box { display: flex; flex-direction: column; min-width: 170px; }
.clock-box b { font-size: 22px; font-family: 'Consolas', monospace; letter-spacing: 2px; color: #4ade80; }
.clock-box span { font-size: 11px; color: #86a391; }
.title-wrap { flex: 1; display: flex; align-items: center; justify-content: center; gap: 16px; }
.title-text { text-align: center; }
.title-text h1 {
  font-size: 24px;
  letter-spacing: 6px;
  background: linear-gradient(180deg, #eafff2, #4ade80);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  text-shadow: 0 0 22px rgba(74, 222, 128, 0.35);
}
.title-text p { font-size: 9px; letter-spacing: 5px; color: rgba(116, 173, 132, 0.7); }
.title-line {
  width: 180px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(74, 222, 128, 0.7));
}
.title-line.right { background: linear-gradient(270deg, transparent, rgba(74, 222, 128, 0.7)); }
.head-right { min-width: 170px; text-align: right; }
.ghost-btn {
  background: transparent;
  border: 1px solid rgba(74, 222, 128, 0.35);
  color: #86efac;
  border-radius: 4px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.ghost-btn:hover { background: rgba(74, 222, 128, 0.12); box-shadow: 0 0 10px rgba(74, 222, 128, 0.25); }

/* ---------- 三栏 ---------- */
.scr-main {
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
  background: rgba(74, 222, 128, 0.05);
  border: 1px solid rgba(74, 222, 128, 0.12);
  border-radius: 6px;
}
.kpi b { font-size: 20px; color: #4ade80; font-family: 'Consolas', monospace; }
.kpi span { font-size: 11px; color: #86a391; }

/* 地图区 */
.p-map :deep(.sp-body) {
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
  background: rgba(74, 222, 128, 0.06);
  border: 1px solid rgba(74, 222, 128, 0.25);
  color: #9ca3af;
  border-radius: 14px;
  font-size: 11px;
  padding: 3px 10px;
  cursor: pointer;
  transition: all 0.2s;
}
.chip.active {
  color: #052e12;
  background: #4ade80;
  border-color: #4ade80;
  box-shadow: 0 0 10px rgba(74, 222, 128, 0.5);
}
.map-wrap { flex: 1; min-height: 0; border-radius: 6px; overflow: hidden; }
.map-strip {
  flex: 0 0 auto;
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 12px;
  color: #b6cdbf;
  background: rgba(74, 222, 128, 0.05);
  border: 1px solid rgba(74, 222, 128, 0.12);
  border-radius: 6px;
  padding: 6px 12px;
}
.map-strip .ok { color: #4ade80; }
.map-strip .warn { color: #fbbf24; }
.strip-time { margin-left: auto; color: #86a391; }

/* 分析行 */
.analysis-row { height: calc(100% - 26px); display: flex; gap: 8px; }
.half { flex: 1; min-width: 0; }
.analysis-caption {
  height: 18px;
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #86a391;
}
.analysis-caption .stress { color: #fbbf24; }

/* 建议信息流 */
.advice-feed { height: 100%; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.feed-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  background: rgba(74, 222, 128, 0.04);
  border-left: 2px solid rgba(74, 222, 128, 0.3);
  border-radius: 4px;
  padding: 7px 10px;
}
.dot { flex: 0 0 6px; width: 6px; height: 6px; border-radius: 50%; margin-top: 6px; background: #4ade80; }
.dot.high { background: #f87171; box-shadow: 0 0 6px rgba(248, 113, 113, 0.8); }
.dot.medium { background: #fbbf24; }
.feed-content {
  font-size: 12px;
  color: #d1fae5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.feed-meta { font-size: 10px; color: #6b8577; margin-top: 3px; }

.empty-tip {
  color: #5f7a6a;
  font-size: 12px;
  text-align: center;
  margin: auto;
}

/* Leaflet 暗色下的控件微调 */
.p-map :deep(.leaflet-control-attribution) {
  background: rgba(7, 19, 12, 0.7);
  color: #5f7a6a;
}
.p-map :deep(.leaflet-control-attribution a) { color: #6b8577; }
</style>
