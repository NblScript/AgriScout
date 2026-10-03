<script setup lang="ts">
/**
 * 待确认（计划 0018，阶段 A 最小版）：所有未完成的「确认」类任务（label），按优先级排序；
 * 确认动作沿用单株时间线的「确认状态」。阶段 B 加侧滑看图、直接提交并跳下一条、手机宽度布局。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Stamp } from '@element-plus/icons-vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import StateTag from '../components/ui/StateTag.vue'
import { softwareLoopApi } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { useFieldsStore } from '../stores/fields'
import { useUiStore } from '../stores/ui'
import { PLAN_TRIGGER_LABELS, PLANT_STATE_LABELS, TASK_STATUS_LABELS, type PlantStateValue, type RevisitTask } from '../types'
import { fieldClock } from '../utils/fieldTime'

const auth = useAuthStore()
const fieldsStore = useFieldsStore()
const ui = useUiStore()

const tasks = ref<RevisitTask[]>([])
const capped = ref(false)
const loading = ref(false)
const fieldFilter = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const result = await softwareLoopApi.openTasks('label', { field_id: fieldFilter.value ?? undefined, limit: 500 })
    tasks.value = result.tasks
    capped.value = result.capped
    if (fieldFilter.value == null) void ui.refreshConfirmCount(true)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void fieldsStore.load().catch(() => { /* 过滤器缺地块列表不致命 */ })
  void load()
})

const fieldNames = computed(() => new Map(fieldsStore.list.map((f) => [f.id, f.name])))

function unitKey(task: RevisitTask): string {
  return (task.parameters.observation_key as string | undefined) ?? '—'
}
function reasons(task: RevisitTask): string[] {
  return ((task.rationale.triggers as string[] | undefined) ?? []).map((t) => PLAN_TRIGGER_LABELS[t] ?? t)
}
function taskState(task: RevisitTask): PlantStateValue | null {
  const state = task.rationale.state as PlantStateValue | undefined
  return state && state in PLANT_STATE_LABELS ? state : null
}
function source(task: RevisitTask): string {
  const value = task.rationale.source
  return value === 'human' ? '人工' : value === 'model' ? '模型占位' : ''
}
function modelScore(task: RevisitTask): string {
  const score = task.rationale.model_score
  return typeof score === 'number' ? score.toFixed(2) : '—'
}
</script>

<template>
  <PageHeader title="待确认" subtitle="模型推荐、等人看照片确认的株；在单株时间线上用「确认状态」提交结论">
    <template #actions>
      <el-select v-model="fieldFilter" placeholder="全部大棚" clearable style="width: 200px" @change="load">
        <el-option v-for="f in fieldsStore.list" :key="f.id" :label="f.name" :value="f.id" />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </template>
  </PageHeader>

  <SectionCard :title="`未完成 ${tasks.length}${capped ? '+' : ''} 条`" subtitle="按优先级从高到低" flush>
    <el-table :data="tasks" v-loading="loading" row-key="id">
      <el-table-column label="株号" width="120">
        <template #default="{ row }">
          <router-link v-if="row.observation_unit_id" :to="`/units/${row.observation_unit_id}`" class="mono">
            {{ unitKey(row) }}
          </router-link>
          <span v-else class="muted">任务 #{{ row.id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="大棚" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ fieldNames.get(row.field_id) ?? `#${row.field_id}` }}</template>
      </el-table-column>
      <el-table-column label="当前状态" width="150">
        <template #default="{ row }">
          <span class="state-cell">
            <StateTag v-if="taskState(row)" :state="taskState(row)!" size="small" />
            <span v-else class="muted">—</span>
            <span v-if="source(row)" class="muted text-12">{{ source(row) }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="原因" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="r in reasons(row)" :key="r" size="small" type="info" effect="plain" class="reason">{{ r }}</el-tag>
          <span v-if="!reasons(row).length" class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="模型分" width="90" align="right">
        <template #default="{ row }"><span class="tabular">{{ modelScore(row) }}</span></template>
      </el-table-column>
      <el-table-column label="计划日" width="110">
        <template #default="{ row }">{{ (row.parameters.plan_date as string | undefined) ?? fieldClock(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="任务" width="110">
        <template #default="{ row }">#{{ row.id }} · {{ TASK_STATUS_LABELS[row.status] ?? row.status }}</template>
      </el-table-column>
      <el-table-column label="" width="120" align="right">
        <template #default="{ row }">
          <router-link v-if="row.observation_unit_id" :to="`/units/${row.observation_unit_id}`">
            <el-button size="small" :type="auth.isViewer ? 'default' : 'primary'" plain>
              {{ auth.isViewer ? '查看' : '去确认' }}
            </el-button>
          </router-link>
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState :icon="Stamp" title="没有等人确认的株" description="生成巡检计划后，模型判为早期或分数超过确认阈值的株会出现在这里。" />
      </template>
    </el-table>
  </SectionCard>
</template>

<style scoped>
.mono { font-family: var(--font-mono); font-size: var(--fs-13); }
.state-cell { display: inline-flex; align-items: center; gap: var(--space-2); }
.reason { margin: 2px 4px 2px 0; }
</style>
