<script setup lang="ts">
/**
 * 大棚详情 · 巡检计划（0015 的计划页挪进来）：按环境风险和每株状态排出某天推给人确认、叶背补拍、低频全覆盖、随机抽查的株，
 * 每条可展开看打分分量。棚内环境曲线在「环境」标签。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import EmptyState from '../../components/ui/EmptyState.vue'
import SectionCard from '../../components/ui/SectionCard.vue'
import StatCard from '../../components/ui/StatCard.vue'
import TaskTypeTag from '../../components/ui/TaskTypeTag.vue'
import { greenhouseApi } from '../../api'
import { errMsg } from '../../api/http'
import { PLAN_LISTS as LISTS, planProgress } from '../../composables/useGreenhouseBoard'
import { useFieldDetail } from '../../composables/useFieldDetail'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import {
  PLAN_LIST_LABELS, PLAN_TRIGGER_LABELS, PLANT_STATE_LABELS, TASK_STATUS_LABELS,
  type PlanItem, type PlanListName, type PlantStateValue,
} from '../../types'
import { fieldClock, fieldDate } from '../../utils/fieldTime'

const d = useFieldDetail()
const auth = useAuthStore()
const ui = useUiStore()
const generating = ref(false)
const activeList = ref<PlanListName>('confirm')
const planDate = ref(fieldDate())

onMounted(() => { void d.plan.load() })

const plan = computed(() => d.plan.data.value)
const isToday = computed(() => plan.value?.plan_date === fieldDate())
const progress = computed(() => planProgress(plan.value))

async function generate() {
  generating.value = true
  try {
    d.plan.data.value = await greenhouseApi.generatePlan(d.fieldId, {
      plan_date: planDate.value,
      created_by: auth.user?.display_name || auth.user?.username || 'system',
    })
    ElMessage.success(`已生成 ${d.plan.data.value.plan_date} 的计划`)
    // 计划写成任务：等人确认的株和角标跟着变
    void d.confirm.load(true)
    void ui.refreshConfirmCount(true)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    generating.value = false
  }
}

function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

/* ---------- 名单 ---------- */
const PART_LABELS: Record<string, string> = {
  model: '模型分', neighbor: '邻株', env: '环境', stale: '叶背陈旧', bad_quality: '上次不合格',
}
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
  <div class="toolbar">
    <div class="plan-meta">
      <template v-if="plan">
        <span class="meta-text"><b>{{ plan.plan_date }}</b> 的计划 · 第 {{ plan.generation ?? '—' }} 次生成于 {{ fieldClock(plan.generated_at) }} · 在册 {{ plan.units }} 株</span>
        <el-tag v-if="!isToday" size="small" type="warning" effect="plain">不是今天的计划</el-tag>
      </template>
      <span v-else class="meta-text">按环境风险和每株状态排出某天要推给人确认、叶背补拍、低频全覆盖、随机抽查的株</span>
    </div>
    <div v-if="!auth.isViewer" class="actions">
      <el-date-picker v-model="planDate" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 150px"
                      aria-label="计划日" />
      <el-button type="primary" :loading="generating" @click="generate">生成计划</el-button>
    </div>
  </div>

  <div v-if="plan" class="kpis">
    <StatCard compact label="生成时环境风险" :value="plan.env.env_missing ? null : plan.env.env_index" :precision="2"
              empty-text="环境数据不足" :hint="plan.env.env_missing ? '补拍预算按中值排' : '近 72 小时，补拍预算随它在 10%–25% 间变化'" />
    <StatCard compact label="叶背补拍窗口" :value="plan.window ? `${plan.window.start}–${plan.window.end}` : null"
              empty-text="没有" :hint="plan.window ? `前夜湿润 ${plan.window.night_wet_hours} 小时` : '前夜湿润不足 4 小时'" />
    <StatCard v-for="name in LISTS" :key="name" compact :label="PLAN_LIST_LABELS[name]" :value="plan[name].length" unit="株"
              :hint="name === 'reshoot' ? `预算 ${plan.reshoot_budget} 株` : name === 'confirm' ? '每天人工预算内' : ''">
      <template #label><TaskTypeTag :type="name" long /></template>
    </StatCard>
  </div>

  <SectionCard v-if="plan" title="名单" :subtitle="`${plan.plan_version}（启发式，参数待田间试用后调整）`" flush>
    <template #actions>
      <span v-if="progress" class="muted text-13">已完成 {{ progress.done }} / {{ progress.total }} 株</span>
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
              <el-descriptions-item v-for="r in detailRows(row)" :key="r.name" :label="r.name">{{ r.value }}</el-descriptions-item>
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
      <template #empty><EmptyState compact :title="`这天没有${PLAN_LIST_LABELS[activeList]}`" /></template>
    </el-table>
  </SectionCard>
  <SectionCard v-else-if="d.plan.loaded.value" title="名单">
    <EmptyState :title="d.plan.error.value || '还没有计划'"
                :description="auth.isViewer ? '由操作员或管理员生成计划。' : '选好计划日，点右上角「生成计划」。'" />
  </SectionCard>
  <el-skeleton v-else animated :rows="6" />
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.plan-meta { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); min-width: 0; }
.meta-text { font-size: var(--fs-13); color: var(--text-secondary); }
.meta-text b { color: var(--text-primary); font-weight: var(--fw-medium); }
.actions { display: flex; align-items: center; gap: var(--space-2); }
.actions :deep(.el-button + .el-button) { margin-left: 0; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: var(--space-3); margin-bottom: var(--space-4); }
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
@media (max-width: 767px) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
