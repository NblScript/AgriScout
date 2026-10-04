<script setup lang="ts">
/**
 * 工作台（计划 0018）：打开系统第一眼看「哪个棚环境风险高、今天要补拍哪些、哪些株等人确认」；点大棚卡片进大棚详情。
 * 数据全部来自 0014/0015 的现有接口，逐个大棚调用；env_index 为空时写「环境数据不足」，不当成低风险。
 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, House, Refresh, Sunrise } from '@element-plus/icons-vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import StatCard from '../components/ui/StatCard.vue'
import StateTag from '../components/ui/StateTag.vue'
import TaskTypeTag from '../components/ui/TaskTypeTag.vue'
import { errMsg } from '../api/http'
import { PLAN_LISTS as LISTS, PLANT_STATES as STATES, stateCounts, useGreenhouseBoard } from '../composables/useGreenhouseBoard'
import { fieldHomePath } from '../layouts/nav'
import { useFieldsStore } from '../stores/fields'
import { useUiStore } from '../stores/ui'
import { ANALYSIS_STATUS_LABELS, FACILITY_LABELS, PLANT_STATE_LABELS, type Field } from '../types'
import { fieldClock, fieldDateLabel, relativeTime } from '../utils/fieldTime'
import { taskModelScore, taskPlantState, taskReasons, taskUnitKey } from '../utils/planTask'

const router = useRouter()
const fieldsStore = useFieldsStore()
const ui = useUiStore()

const {
  loading, loaded, cards, openFields, confirmTasks, confirmCapped, recent, confirmByField, todayPlan, load: loadBoard,
} = useGreenhouseBoard()

async function load() {
  try {
    await loadBoard()
    void ui.refreshConfirmCount(true)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
onMounted(load)

/* ---------- 每张大棚卡 ---------- */
const fieldNames = computed(() => new Map(fieldsStore.list.map((f) => [f.id, f.name])))

function share(count: number, total: number): string {
  return total ? `${(count / total) * 100}%` : '0%'
}
function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

/* ---------- 顶部指标 ---------- */
const topRisk = computed(() => cards.value.find((c) => c.env?.index.env_index != null) ?? null)
const reshootToday = computed(() => cards.value.reduce((sum, c) => sum + (todayPlan(c)?.reshoot.length ?? 0), 0))
const plannedToday = computed(() => cards.value.filter((c) => todayPlan(c)).length)
const attention = computed(() => cards.value.reduce((acc, c) => {
  const counts = stateCounts(c.states)
  return { early: acc.early + counts.early, symptomatic: acc.symptomatic + counts.symptomatic }
}, { early: 0, symptomatic: 0 }))

function openField(field: Field) {
  void router.push(fieldHomePath(field))
}
</script>

<template>
  <PageHeader title="工作台" :subtitle="`${fieldDateLabel()} · 大棚 ${cards.length} 个 · 大田 ${openFields.length} 块`">
    <template #actions>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </template>
  </PageHeader>

  <div class="kpis">
    <StatCard label="最高环境风险（近 72 小时）" :value="topRisk?.env?.index.env_index ?? null" :precision="2"
              :empty-text="loaded ? '环境数据不足' : '—'" :loading="loading && !loaded"
              :hint="topRisk ? topRisk.field.name : '没有大棚有足够的温湿度读数'" />
    <StatCard label="待确认" :value="loaded ? confirmTasks.length : null" unit="株" :loading="loading && !loaded"
              :hint="confirmCapped ? '超过 500 条，只统计前 500 条' : '模型推荐、等人确认的株'" />
    <StatCard label="今日叶背补拍" :value="loaded ? reshootToday : null" unit="株" :loading="loading && !loaded"
              :hint="`${plannedToday} / ${cards.length} 个大棚已生成今日计划`" />
    <StatCard label="需关注的株" :value="loaded ? attention.early + attention.symptomatic : null" unit="株"
              :loading="loading && !loaded"
              :hint="`早期 ${attention.early} · 明显 ${attention.symptomatic}（含模型占位）`" />
  </div>

  <section class="block">
    <div class="block-head">
      <h2>大棚</h2>
      <span class="muted text-13">按环境风险从高到低；点卡片进大棚详情</span>
    </div>
    <div v-if="cards.length" class="gh-grid">
      <article v-for="card in cards" :key="card.field.id" class="gh-card" tabindex="0" role="link"
               :aria-label="`${card.field.name}，进入大棚详情`"
               @click="openField(card.field)" @keydown.enter="openField(card.field)">
        <header class="gh-head">
          <div class="gh-title">
            <h3>{{ card.field.name }}</h3>
            <p class="muted text-12">
              {{ FACILITY_LABELS[card.field.facility_type ?? 'open_field'] }} · 在册 {{ card.states.length }} 株 ·
              最近巡检 {{ relativeTime(card.lastPatrol?.started_at) }}
            </p>
          </div>
          <el-icon class="gh-go"><ArrowRight /></el-icon>
        </header>

        <div class="gh-env">
          <div class="gh-env-main">
            <span class="gh-label">环境风险</span>
            <template v-if="card.env?.index.env_index != null">
              <span class="gh-env-value">{{ card.env.index.env_index.toFixed(2) }}</span>
              <span class="meter" aria-hidden="true"><i :style="{ width: share(card.env.index.env_index, 1) }" /></span>
            </template>
            <el-tooltip v-else :content="card.env?.index.reason ?? '没有温湿度读数'" placement="top">
              <span class="gh-env-missing">环境数据不足</span>
            </el-tooltip>
          </div>
          <p class="muted text-12">
            <template v-if="card.env">
              适宜 {{ card.env.index.favorable_hours }} 小时 · 湿润 {{ card.env.index.wet_hours }} 小时 · 读数覆盖 {{ pct(card.env.index.coverage) }}
            </template>
            <template v-else>没有拿到环境数据</template>
          </p>
          <p class="gh-window text-12" :class="{ on: card.env?.morning_window }">
            <el-icon><Sunrise /></el-icon>
            <template v-if="card.env?.morning_window">
              清晨窗口 {{ card.env.morning_window.start }}–{{ card.env.morning_window.end }}（前夜湿润 {{ card.env.morning_window.night_wet_hours }} 小时）
            </template>
            <template v-else>今天没有清晨叶背窗口</template>
          </p>
        </div>

        <div class="gh-plan">
          <span class="gh-label">今日计划</span>
          <div v-if="todayPlan(card)" class="gh-tags">
            <TaskTypeTag v-for="name in LISTS" :key="name" :type="name" :count="todayPlan(card)![name].length" />
          </div>
          <p v-else class="muted text-12">
            今日未生成<template v-if="card.plan">（最近一次 {{ card.plan.plan_date }}）</template>
          </p>
        </div>

        <div class="gh-states">
          <div class="gh-states-head">
            <span class="gh-label">株状态</span>
            <span class="text-12">待确认 <b class="tabular">{{ confirmByField.get(card.field.id) ?? 0 }}</b> 株</span>
          </div>
          <div v-if="card.states.length" class="dist" role="img"
               :aria-label="STATES.map((s) => `${PLANT_STATE_LABELS[s]} ${stateCounts(card.states)[s]} 株`).join('，')">
            <i v-for="s in STATES" :key="s" :class="`d-${s}`"
               :style="{ width: share(stateCounts(card.states)[s], card.states.length) }" />
          </div>
          <div v-if="card.states.length" class="gh-legend">
            <span v-for="s in STATES" :key="s" class="gh-legend-item">
              <StateTag :state="s" size="small" /><b class="tabular">{{ stateCounts(card.states)[s] }}</b>
            </span>
          </div>
          <p v-else class="muted text-12">还没有株档案</p>
        </div>
      </article>
    </div>
    <SectionCard v-else-if="loaded">
      <EmptyState :icon="House" title="还没有大棚" description="在「大棚与地块」里新建地块，设施类型选日光温室或塑料大棚，再批量建株档案。">
        <el-button type="primary" @click="router.push('/fields')">去建大棚</el-button>
      </EmptyState>
    </SectionCard>
    <div v-else class="gh-grid"><el-skeleton v-for="i in 2" :key="i" animated :rows="6" class="gh-card" /></div>
  </section>

  <div class="two-col">
    <SectionCard title="待我确认" :subtitle="`未完成的确认任务，按优先级；共 ${confirmTasks.length}${confirmCapped ? '+' : ''} 条`" flush>
      <template #actions>
        <router-link to="/confirm" class="more">全部<el-icon><ArrowRight /></el-icon></router-link>
      </template>
      <el-table :data="confirmTasks.slice(0, 10)" size="small" v-loading="loading && !loaded">
        <el-table-column label="株号" width="110">
          <template #default="{ row }">
            <router-link v-if="row.observation_unit_id" :to="`/units/${row.observation_unit_id}`" class="mono">{{ taskUnitKey(row) }}</router-link>
            <span v-else class="muted">任务 #{{ row.id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大棚" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ fieldNames.get(row.field_id) ?? `#${row.field_id}` }}</template>
        </el-table-column>
        <el-table-column label="当前状态" width="96">
          <template #default="{ row }">
            <StateTag v-if="taskPlantState(row)" :state="taskPlantState(row)!" size="small" />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="原因" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ taskReasons(row).join('、') || '—' }}</template>
        </el-table-column>
        <el-table-column label="模型分" width="76" align="right">
          <template #default="{ row }"><span class="tabular">{{ taskModelScore(row) }}</span></template>
        </el-table-column>
        <template #empty><EmptyState compact title="没有等人确认的株" /></template>
      </el-table>
    </SectionCard>

    <SectionCard title="最近巡检" flush>
      <template #actions>
        <router-link to="/patrols" class="more">全部<el-icon><ArrowRight /></el-icon></router-link>
      </template>
      <ul v-if="recent.length" class="patrol-list">
        <li v-for="p in recent" :key="p.id">
          <router-link :to="`/patrols/${p.id}`" class="patrol-row">
            <span class="patrol-main">
              <b>#{{ p.id }} · {{ p.field_name ?? `地块 #${p.field_id}` }}</b>
              <span class="muted text-12">{{ fieldClock(p.started_at) }} · {{ p.device_code ?? '未登记设备' }}</span>
            </span>
            <el-tag size="small" effect="plain"
                    :type="p.analysis_status === 'done' ? 'success' : p.analysis_status === 'error' ? 'danger' : p.analysis_status === 'running' ? 'warning' : 'info'">
              {{ ANALYSIS_STATUS_LABELS[p.analysis_status] ?? p.analysis_status }}
            </el-tag>
          </router-link>
        </li>
      </ul>
      <EmptyState v-else-if="loaded" compact title="还没有巡检" description="小车上传巡检包后在这里出现" />
    </SectionCard>
  </div>

  <SectionCard v-if="openFields.length" title="大田" subtitle="小麦方法验证资产（D16 保留），只看最近巡检" class="open-fields">
    <div class="of-list">
      <button v-for="item in openFields" :key="item.field.id" type="button" class="of-item" @click="openField(item.field)">
        <b>{{ item.field.name }}</b>
        <span class="muted text-12">
          <template v-if="item.lastPatrol">最近巡检 #{{ item.lastPatrol.id }} · {{ fieldClock(item.lastPatrol.started_at) }}</template>
          <template v-else>还没有巡检</template>
        </span>
      </button>
    </div>
  </SectionCard>
</template>

<style scoped>
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-4); margin-bottom: var(--space-6); }
.block { margin-bottom: var(--space-6); }
.block-head { display: flex; align-items: baseline; gap: var(--space-3); margin-bottom: var(--space-3); }
.block-head h2 { margin: 0; font-size: var(--fs-16); line-height: var(--lh-16); font-weight: var(--fw-semibold); }

/* 棚少时卡片不拉得过宽（最宽 520），棚多时三列铺满 */
.gh-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 520px)); gap: var(--space-4); }
.gh-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
  cursor: pointer;
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}
.gh-card:hover { border-color: var(--brand-300); box-shadow: var(--shadow-2); }
.gh-card:focus-visible { outline: 2px solid var(--brand-300); outline-offset: 2px; }
.gh-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.gh-title { min-width: 0; }
.gh-title h3 { margin: 0 0 2px; font-size: var(--fs-16); line-height: var(--lh-16); font-weight: var(--fw-semibold); }
.gh-title p { margin: 0; }
.gh-go { color: var(--text-placeholder); margin-top: 4px; }
.gh-card:hover .gh-go { color: var(--brand-600); }
.gh-label { font-size: var(--fs-12); color: var(--text-secondary); }

.gh-env { padding: var(--space-3) var(--space-4); background: var(--bg-subtle); border-radius: var(--radius-md); }
.gh-env p { margin: var(--space-1) 0 0; }
.gh-env-main { display: flex; align-items: center; gap: var(--space-3); }
.gh-env-value { font-size: var(--fs-24); line-height: var(--lh-24); font-weight: var(--fw-semibold); font-variant-numeric: tabular-nums; }
.gh-env-missing {
  font-size: var(--fs-14);
  font-weight: var(--fw-medium);
  color: var(--info-ink);
  padding: 2px var(--space-2);
  border: 1px dashed var(--neutral-400);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
}
.meter { flex: 1; height: 6px; border-radius: 3px; background: var(--neutral-200); overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--warning); border-radius: 3px; }
.gh-window { display: flex; align-items: center; gap: var(--space-1); color: var(--text-secondary); }
.gh-window.on { color: var(--warning-ink); }

.gh-plan { display: flex; flex-direction: column; gap: var(--space-2); }
.gh-plan p { margin: 0; }
.gh-tags { display: flex; flex-wrap: wrap; gap: var(--space-2); }

.gh-states { display: flex; flex-direction: column; gap: var(--space-2); }
.gh-states p { margin: 0; }
.gh-states-head { display: flex; justify-content: space-between; align-items: baseline; }
.dist { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--neutral-100); gap: 2px; }
.dist i { display: block; height: 100%; min-width: 0; }
.dist i[style*='width: 0%'] { display: none; }
.d-healthy { background: var(--state-healthy); }
.d-early { background: var(--state-early); }
.d-symptomatic { background: var(--state-symptomatic); }
.d-unknown { background: repeating-linear-gradient(135deg, var(--state-unknown) 0 3px, var(--neutral-100) 3px 5px); }
.gh-legend { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-3); }
.gh-legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-13); }

.two-col {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  align-items: start;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}
.more { display: inline-flex; align-items: center; gap: 2px; font-size: var(--fs-13); }
.mono { font-family: var(--font-mono); font-size: var(--fs-13); }
.patrol-list { list-style: none; margin: 0; padding: 0; }
.patrol-list li + li { border-top: 1px solid var(--border); }
.patrol-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  color: var(--text-primary);
}
.patrol-row:hover { background: var(--bg-hover); }
.patrol-main { display: flex; flex-direction: column; min-width: 0; }
.patrol-main b { font-weight: var(--fw-medium); font-size: var(--fs-14); }

.of-list { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.of-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 220px;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  font: inherit;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}
.of-item:hover { border-color: var(--brand-300); background: var(--bg-hover); }

@media (max-width: 1279px) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .two-col { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 767px) {
  .kpis { gap: var(--space-3); }
  .gh-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
