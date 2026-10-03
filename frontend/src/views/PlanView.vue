<script setup lang="ts">
/**
 * 巡检计划（计划 0015；0018 换新样式）：棚内环境曲线 + 今日四张名单（推给人确认 / 叶背补拍 / 低频全覆盖 / 随机抽查），
 * 每条可展开看打分分量。阶段 B 挪进大棚详情的「巡检计划」标签页。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Files, Refresh } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import StatCard from '../components/ui/StatCard.vue'
import TaskTypeTag from '../components/ui/TaskTypeTag.vue'
import { fieldsApi, greenhouseApi } from '../api'
import { errMsg } from '../api/http'
import { useBreadcrumb } from '../composables/useBreadcrumb'
import { useAuthStore } from '../stores/auth'
import { cssVar } from '../styles/tokens'
import { chartBase, hourlyEnvOption } from '../utils/envChart'
import {
  FACILITY_LABELS, PLAN_LIST_LABELS, PLAN_TRIGGER_LABELS, PLANT_STATE_LABELS, TASK_STATUS_LABELS,
  type EnvSummary, type Field, type PatrolPlan, type PlanItem, type PlanListName, type PlantStateValue,
} from '../types'
import { fieldClock, fieldDate } from '../utils/fieldTime'

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
const planDate = ref(fieldDate())

useBreadcrumb(() => [
  { label: '大棚与地块', to: '/fields' },
  { label: field.value?.name ?? `地块 #${fieldId}` },
  { label: '巡检计划' },
])

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
function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}
const hasReadings = computed(() => !!env.value && env.value.hourly.some((h) => !h.missing))

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
    xAxis: { type: 'category', data: days.map((d) => d.field_date.slice(5)), axisLine: base.axisLine, axisTick: { show: false }, axisLabel: base.axisLabel },
    yAxis: { type: 'value', name: '小时', max: 24, nameTextStyle: base.axisLabel, axisLabel: base.axisLabel, splitLine: base.splitLine },
    series: [
      { name: '适宜时长', type: 'bar', barMaxWidth: 14, data: days.map((d) => d.favorable_hours), color: cssVar('--chart-warm', '#c8691f') },
      { name: '湿润时长', type: 'bar', barMaxWidth: 14, data: days.map((d) => d.wet_hours), color: cssVar('--chart-wet', '#2f6fb0') },
      { name: '夜间湿润', type: 'bar', barMaxWidth: 14, data: days.map((d) => d.night_wet_hours), color: cssVar('--chart-night', '#1f8a83') },
    ],
  }
})

/* ---------- 计划 ---------- */
const LISTS: PlanListName[] = ['confirm', 'reshoot', 'coverage', 'random']
const PART_LABELS: Record<string, string> = {
  model: '模型分', neighbor: '邻株', env: '环境', stale: '叶背陈旧', bad_quality: '上次不合格',
}
const isToday = computed(() => plan.value?.plan_date === fieldDate())
const items = computed<PlanItem[]>(() => (plan.value ? plan.value[activeList.value] : []))
function triggers(item: PlanItem): string[] {
  return ((item.rationale.triggers as string[] | undefined) ?? []).map((t) => PLAN_TRIGGER_LABELS[t] ?? t)
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
      { name: '环境指数', value: inputs.env_missing ? '环境数据不足（按 0.5 计）' : fmt(inputs.env_index) },
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
  <PageHeader :title="field?.name ?? `地块 #${fieldId}`"
              subtitle="巡检计划：按环境风险和每株状态排出今天推给人确认、叶背补拍、低频全覆盖、随机抽查的株">
    <template #meta>
      <el-tag v-if="field" size="small" effect="plain">{{ FACILITY_LABELS[field.facility_type ?? 'open_field'] }}</el-tag>
      <span v-if="plan" class="meta-text">在册 {{ plan.units }} 株</span>
      <span v-if="plan?.generated_at" class="meta-text">
        {{ plan.plan_date }} 的计划 · 第 {{ plan.generation }} 次生成于 {{ fieldClock(plan.generated_at) }}
      </span>
      <el-tag v-if="plan && !isToday" size="small" type="warning" effect="plain">不是今天的计划</el-tag>
    </template>
    <template #actions>
      <el-button :icon="Files" @click="router.push({ name: 'field-units', params: { id: fieldId } })">株档案</el-button>
      <el-date-picker v-model="planDate" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 150px"
                      aria-label="计划日" />
      <el-button v-if="!auth.isViewer" type="primary" :loading="generating" @click="generate">生成计划</el-button>
      <el-button :icon="Refresh" :loading="loading" aria-label="刷新" @click="load" />
    </template>
  </PageHeader>

  <div class="kpis">
    <StatCard compact label="环境风险 · 近 72 小时" :value="env?.index.env_index ?? null" :precision="2" :loading="loading && !env"
              :empty-text="env ? '环境数据不足' : '—'"
              :hint="env ? `适宜 ${env.index.favorable_hours} h · 湿润 ${env.index.wet_hours} h · 覆盖 ${pct(env.index.coverage)}` : ''" />
    <StatCard compact label="清晨叶背窗口" :value="env?.morning_window ? `${env.morning_window.start}–${env.morning_window.end}` : null"
              :empty-text="env ? '今天没有' : '—'" :loading="loading && !env"
              :hint="env?.morning_window ? `前夜湿润 ${env.morning_window.night_wet_hours} 小时` : '前夜湿润不足 4 小时'" />
    <StatCard v-for="name in LISTS" :key="name" compact :label="PLAN_LIST_LABELS[name]" :value="plan ? plan[name].length : null" unit="株"
              :hint="name === 'reshoot' && plan ? `预算 ${plan.reshoot_budget} 株` : name === 'confirm' ? '每天人工预算内' : ''">
      <template #label><TaskTypeTag :type="name" long /></template>
    </StatCard>
  </div>

  <SectionCard title="棚内环境" subtitle="近 7 天逐时读数与按田间日期汇总的时长（缺测不插值，曲线断开）；环境风险只看最近 72 小时" class="block">
    <div v-if="hasReadings" class="charts">
      <div class="chart"><EChart :option="hourlyOption" /></div>
      <div class="chart narrow"><EChart :option="dailyOption" /></div>
    </div>
    <EmptyState v-else-if="!loading" compact title="还没有温湿度读数"
                description="记录仪导出的 CSV 可用 rover/env_upload.py 上传；没有读数时环境风险按「环境数据不足」处理，不当成低风险。" />
  </SectionCard>

  <SectionCard v-if="plan" title="今日名单" :subtitle="`${plan.plan_version}（启发式，参数待田间试用后调整）`" flush class="block">
    <template #actions>
      <span v-if="plan.window" class="muted text-13">叶背补拍建议 {{ plan.window.start }}–{{ plan.window.end }}</span>
    </template>
    <el-tabs v-model="activeList" class="list-tabs">
      <el-tab-pane v-for="name in LISTS" :key="name" :name="name">
        <template #label><TaskTypeTag :type="name" long :count="plan[name].length" /></template>
      </el-tab-pane>
    </el-tabs>
    <el-table :data="items" row-key="task_id">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand">
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item v-for="d in detailRows(row)" :key="d.name" :label="d.name">{{ d.value }}</el-descriptions-item>
            </el-descriptions>
            <div v-if="parts(row).length" class="parts">
              分量：<span v-for="p in parts(row)" :key="p.name" class="part">{{ p.name }} <b class="tabular">{{ p.value.toFixed(3) }}</b></span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="株号" width="120">
        <template #default="{ row }">
          <router-link :to="{ name: 'unit-timeline', params: { id: row.unit_id } }" class="mono">{{ row.key }}</router-link>
        </template>
      </el-table-column>
      <el-table-column label="分数" width="90" align="right">
        <template #default="{ row }"><span class="tabular">{{ row.score.toFixed(3) }}</span></template>
      </el-table-column>
      <el-table-column label="原因" min-width="240">
        <template #default="{ row }">
          <el-tag v-for="t in triggers(row)" :key="t" size="small" type="info" effect="plain" class="trigger">{{ t }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="任务" width="140">
        <template #default="{ row }"><span class="muted">#{{ row.task_id }}</span> · {{ TASK_STATUS_LABELS[row.task_status] ?? row.task_status }}</template>
      </el-table-column>
      <template #empty><EmptyState compact :title="`今天没有${PLAN_LIST_LABELS[activeList]}`" /></template>
    </el-table>
  </SectionCard>
  <SectionCard v-else-if="!loading" title="今日名单" class="block">
    <EmptyState :title="planNote || '还没有计划'"
                :description="auth.isViewer ? '由操作员或管理员生成计划。' : '选好计划日，点右上角「生成计划」。'" />
  </SectionCard>
</template>

<style scoped>
.meta-text { font-size: var(--fs-13); color: var(--text-secondary); }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: var(--space-3); margin-bottom: var(--space-5); }
.block { margin-bottom: var(--space-5); }
.charts { display: flex; gap: var(--space-4); }
.chart { flex: 2; min-width: 0; height: 260px; }
.chart.narrow { flex: 1; }
.list-tabs { padding: 0 var(--space-5); }
.list-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
.list-tabs :deep(.el-tabs__nav-wrap::after) { height: 1px; background: var(--border); }
.list-tabs :deep(.el-tabs__item) { height: 48px; }
.mono { font-family: var(--font-mono); font-size: var(--fs-13); }
.trigger { margin: 2px 4px 2px 0; }
.expand { padding: var(--space-2) var(--space-6); }
.parts { margin-top: var(--space-2); font-size: var(--fs-12); color: var(--text-regular); }
.part { margin-right: var(--space-3); }
@media (max-width: 1279px) {
  .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1023px) {
  .charts { flex-direction: column; }
  .chart.narrow { height: 220px; }
}
@media (max-width: 767px) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
