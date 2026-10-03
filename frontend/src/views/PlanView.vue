<script setup lang="ts">
/** 巡检计划（计划 0015）：棚内环境曲线 + 今日四张名单（推给人确认 / 叶背补拍 / 低频全覆盖 / 随机抽查），每条可展开看打分分量。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import EChart from '../components/EChart.vue'
import { fieldsApi, greenhouseApi } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import {
  PLAN_LIST_LABELS, PLANT_STATE_LABELS,
  type EnvSummary, type Field, type PatrolPlan, type PlanItem, type PlanListName, type PlantStateValue,
} from '../types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const fieldId = Number(route.params.id)

const field = ref<Field | null>(null)
const env = ref<EnvSummary | null>(null)
const plan = ref<PatrolPlan | null>(null)
const planNote = ref('')
const loading = ref(false)
const generating = ref(false)
const activeList = ref<PlanListName>('confirm')

/** 田间日期（UTC+8），与后端 field_date 同口径 */
function fieldToday(): string {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10)
}
const planDate = ref(fieldToday())

async function load() {
  loading.value = true
  try {
    const [f, e] = await Promise.all([fieldsApi.get(fieldId), greenhouseApi.env(fieldId)])
    field.value = f
    env.value = e
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
  try {
    plan.value = await greenhouseApi.latestPlan(fieldId)
    planNote.value = ''
  } catch (e) {
    plan.value = null
    planNote.value = errMsg(e)
  }
}
onMounted(() => {
  if (!Number.isInteger(fieldId) || fieldId <= 0) {
    void router.replace({ name: 'fields' })
    return
  }
  void load()
})

async function generate() {
  generating.value = true
  try {
    plan.value = await greenhouseApi.generatePlan(fieldId, {
      plan_date: planDate.value,
      created_by: auth.user?.display_name || auth.user?.username || 'system',
    })
    planNote.value = ''
    ElMessage.success(`已生成 ${plan.value.plan_date} 的计划`)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    generating.value = false
  }
}

/* ---------- 环境 ---------- */
/** 田间时区（UTC+8）的「月/日 时」，不随浏览器时区漂移 */
function localParts(iso: string): { day: string; hour: number; minute: number } {
  const d = new Date(Date.parse(iso) + 8 * 3600 * 1000)
  return { day: `${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`,
           hour: d.getUTCHours(), minute: d.getUTCMinutes() }
}
function hourLabel(iso: string): string {
  const { day, hour } = localParts(iso)
  return `${day} ${String(hour).padStart(2, '0')}时`
}
function clockText(iso: string): string {
  const { day, hour, minute } = localParts(iso)
  return `${day} ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}
function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

const hourlyOption = computed<EChartsOption>(() => {
  const hours = env.value?.hourly ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['温度 ℃', '相对湿度 %', '露点差 ℃'], top: 0 },
    grid: { left: 48, right: 48, top: 32, bottom: 28 },
    xAxis: {
      type: 'category',
      data: hours.map((h) => hourLabel(h.hour)),
      // 只在田间日期的零点标刻度
      axisLabel: { interval: (index: number) => localParts(hours[index].hour).hour === 0, formatter: (v: string) => v.slice(0, 5) },
    },
    yAxis: [
      { type: 'value', name: '℃', splitLine: { lineStyle: { type: 'dashed' } } },
      { type: 'value', name: '%', min: 0, max: 100 },
    ],
    series: [
      // 缺测小时为 null，曲线断开而不是插值
      { name: '温度 ℃', type: 'line', showSymbol: false, data: hours.map((h) => h.temp_c), color: '#c0392b' },
      { name: '相对湿度 %', type: 'line', showSymbol: false, yAxisIndex: 1, data: hours.map((h) => h.humidity_pct), color: '#2c7be5' },
      { name: '露点差 ℃', type: 'line', showSymbol: false, data: hours.map((h) => h.dewpoint_depression_min), color: '#7f8c8d' },
    ],
  }
})

const dailyOption = computed<EChartsOption>(() => {
  const days = env.value?.daily ?? []
  return {
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
    legend: { data: ['适宜时长', '湿润时长', '夜间湿润'], top: 0 },
    grid: { left: 40, right: 16, top: 32, bottom: 28 },
    xAxis: { type: 'category', data: days.map((d) => d.field_date.slice(5)) },
    yAxis: { type: 'value', name: '小时', max: 24 },
    series: [
      { name: '适宜时长', type: 'bar', data: days.map((d) => d.favorable_hours), color: '#e67e22' },
      { name: '湿润时长', type: 'bar', data: days.map((d) => d.wet_hours), color: '#2c7be5' },
      { name: '夜间湿润', type: 'bar', data: days.map((d) => d.night_wet_hours), color: '#16a085' },
    ],
  }
})

/* ---------- 计划 ---------- */
const LISTS: PlanListName[] = ['confirm', 'reshoot', 'coverage', 'random']
const TRIGGER_LABELS: Record<string, string> = {
  model_early: '模型判早期',
  model_score_over_confirm_threshold: '模型分超确认阈值',
  top_reshoot_score: '补拍分靠前',
  last_under_rejected: '上次叶背不合格',
  morning_window: '清晨窗口',
  coverage_due: '超过全覆盖周期',
  never_seen: '从未拍到',
  random_spot_check: '随机抽查',
}
const PART_LABELS: Record<string, string> = {
  model: '模型分', neighbor: '邻株', env: '环境', stale: '叶背陈旧', bad_quality: '上次不合格',
}
const STATUS_LABELS: Record<string, string> = {
  queued: '待领取', assigned: '已分配', running: '执行中', completed: '已完成', cancelled: '已取消',
}
const items = computed<PlanItem[]>(() => (plan.value ? plan.value[activeList.value] : []))
function triggers(item: PlanItem): string[] {
  return ((item.rationale.triggers as string[] | undefined) ?? []).map((t) => TRIGGER_LABELS[t] ?? t)
}
function parts(item: PlanItem): { name: string; value: number }[] {
  const raw = (item.rationale.parts as Record<string, number> | undefined) ?? {}
  return Object.entries(raw).map(([k, v]) => ({ name: PART_LABELS[k] ?? k, value: v }))
}
function detailRows(item: PlanItem): { name: string; value: string }[] {
  const r = item.rationale as Record<string, unknown>
  const inputs = (r.inputs as Record<string, unknown> | undefined) ?? {}
  const fmt = (v: unknown) => (v == null ? '—' : typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : String(v))
  if (item.list_name === 'reshoot') {
    return [
      { name: '模型分', value: fmt(inputs.model_score) },
      { name: '邻株最高分', value: fmt(inputs.neighbor_max_score) },
      { name: '环境指数', value: inputs.env_missing ? '无环境信息（按 0.5 计）' : fmt(inputs.env_index) },
      { name: '距上次合格叶背（天）', value: fmt(inputs.days_since_under_ok) },
    ]
  }
  if (item.list_name === 'confirm') {
    return [
      { name: '当前状态', value: `${PLANT_STATE_LABELS[r.state as PlantStateValue] ?? fmt(r.state)}（${r.source === 'human' ? '人工' : r.source === 'model' ? '模型占位' : '无'}）` },
      { name: '模型分 / 确认阈值', value: `${fmt(r.model_score)} / ${fmt(r.confirm_threshold)}` },
      { name: '人工预算', value: `${fmt(r.rank)} / ${fmt(r.human_budget)}（候选 ${fmt(r.candidates)}）` },
    ]
  }
  if (item.list_name === 'coverage') {
    return [{ name: '距上次看到（天）', value: fmt(r.days_since_seen) }, { name: '全覆盖周期（天）', value: fmt(r.coverage_period_days) }]
  }
  return [{ name: '抽查池', value: `${fmt(r.pool)} 株，比例 ${pct(r.random_ratio as number)}` }, { name: '种子', value: fmt(r.seed) }]
}
</script>

<template>
  <div class="head">
    <el-button :icon="ArrowLeft" text @click="router.push({ name: 'fields' })">地块</el-button>
    <span class="title">{{ field?.name ?? `地块 #${fieldId}` }} · 巡检计划</span>
    <span class="spacer" />
    计划日
    <el-date-picker v-model="planDate" type="date" value-format="YYYY-MM-DD" size="small" style="width: 140px" :clearable="false" />
    <el-button type="primary" size="small" :loading="generating" :disabled="auth.isViewer" @click="generate">生成计划</el-button>
    <el-button :icon="Refresh" circle size="small" title="刷新" @click="load" />
  </div>

  <div v-loading="loading" class="env">
    <el-descriptions :column="4" border size="small" class="summary">
      <el-descriptions-item label="环境指数（近 72 小时）">
        <template v-if="env?.index.env_index != null">{{ env.index.env_index.toFixed(2) }}</template>
        <el-tooltip v-else :content="env?.index.reason ?? '没有读数'" placement="top">
          <el-tag type="info" size="small" effect="plain">无环境信息</el-tag>
        </el-tooltip>
      </el-descriptions-item>
      <el-descriptions-item label="适宜 / 湿润时长">
        {{ env ? `${env.index.favorable_hours} / ${env.index.wet_hours} 小时` : '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="读数覆盖率">{{ pct(env?.index.coverage) }}</el-descriptions-item>
      <el-descriptions-item label="清晨窗口">
        <template v-if="env?.morning_window">
          {{ env.morning_window.date }} {{ env.morning_window.start }}–{{ env.morning_window.end }}
          <div class="sub">{{ env.morning_window.reason }}</div>
        </template>
        <span v-else class="empty">无</span>
      </el-descriptions-item>
    </el-descriptions>
    <div v-if="env && env.hourly.some((h) => !h.missing)" class="charts">
      <div class="chart"><EChart :option="hourlyOption" /></div>
      <div class="chart narrow"><EChart :option="dailyOption" /></div>
    </div>
    <el-empty v-else description="这块地还没有温湿度读数（记录仪 CSV 可用 rover/env_upload.py 上传）" :image-size="60" />
  </div>

  <template v-if="plan">
    <div class="plan-meta">
      {{ plan.plan_date }} 的计划 · 在册 {{ plan.units }} 株 · 补拍预算 {{ plan.reshoot_budget }} 株
      <template v-if="plan.window"> · 叶背补拍建议 {{ plan.window.start }}–{{ plan.window.end }}</template>
      <span class="muted">
        · {{ plan.plan_version }}（启发式，参数待田间试用后调整）
        <template v-if="plan.generated_at"> · 第 {{ plan.generation }} 次生成于 {{ clockText(plan.generated_at) }}</template>
      </span>
    </div>
    <el-tabs v-model="activeList">
      <el-tab-pane v-for="name in LISTS" :key="name" :name="name" :label="`${PLAN_LIST_LABELS[name]}（${plan[name].length}）`" />
    </el-tabs>
    <el-table :data="items" border size="small" row-key="task_id" :empty-text="`今天没有${PLAN_LIST_LABELS[activeList]}`">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand">
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item v-for="d in detailRows(row)" :key="d.name" :label="d.name">{{ d.value }}</el-descriptions-item>
            </el-descriptions>
            <div v-if="parts(row).length" class="parts">
              分量：<span v-for="p in parts(row)" :key="p.name" class="part">{{ p.name }} {{ p.value.toFixed(3) }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="株号" width="120">
        <template #default="{ row }">
          <el-link type="primary" @click="router.push({ name: 'unit-timeline', params: { id: row.unit_id } })">{{ row.key }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="分数" width="80" align="right">
        <template #default="{ row }">{{ row.score.toFixed(3) }}</template>
      </el-table-column>
      <el-table-column label="原因" min-width="220">
        <template #default="{ row }">
          <el-tag v-for="t in triggers(row)" :key="t" size="small" effect="plain" class="trigger">{{ t }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="任务" width="110">
        <template #default="{ row }">#{{ row.task_id }} · {{ STATUS_LABELS[row.task_status] ?? row.task_status }}</template>
      </el-table-column>
    </el-table>
  </template>
  <el-empty v-else :description="planNote || '还没有计划'" :image-size="60" />
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-size: 13px; color: var(--el-text-color-regular); }
.title { font-size: 16px; font-weight: 600; color: var(--el-text-color-primary); }
.spacer { flex: 1; }
.env { margin-bottom: 16px; }
.summary { margin-bottom: 12px; }
.charts { display: flex; gap: 12px; }
.chart { flex: 2; height: 240px; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; padding: 8px; }
.chart.narrow { flex: 1; }
.plan-meta { font-size: 13px; color: var(--el-text-color-regular); margin-bottom: 4px; }
.muted, .sub, .empty { color: var(--el-text-color-secondary); font-size: 12px; }
.trigger { margin-right: 4px; }
.expand { padding: 4px 48px; }
.parts { margin-top: 8px; font-size: 12px; color: var(--el-text-color-regular); }
.part { margin-right: 12px; }
</style>
