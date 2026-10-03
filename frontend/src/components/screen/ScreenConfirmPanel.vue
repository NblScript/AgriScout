<script setup lang="ts">
/** 展示屏 · 等人确认：本棚未完成的「确认」任务前几条（按优先级），株号、当前状态、原因、模型分。 */
import { computed } from 'vue'
import SectionCard from '../ui/SectionCard.vue'
import StateTag from '../ui/StateTag.vue'
import { PLAN_TRIGGER_LABELS, PLANT_STATE_LABELS, type PlantStateValue, type RevisitTask } from '../../types'

const props = withDefaults(defineProps<{ tasks: RevisitTask[]; limit?: number }>(), { limit: 5 })

const shown = computed(() => props.tasks.slice(0, props.limit))
const rest = computed(() => Math.max(props.tasks.length - props.limit, 0))

function unitKey(task: RevisitTask): string {
  return (task.parameters.observation_key as string | undefined) ?? `任务 #${task.id}`
}
function taskState(task: RevisitTask): PlantStateValue | null {
  const state = task.rationale.state as PlantStateValue | undefined
  return state && state in PLANT_STATE_LABELS ? state : null
}
function reasons(task: RevisitTask): string {
  const triggers = (task.rationale.triggers as string[] | undefined) ?? []
  return triggers.map((t) => PLAN_TRIGGER_LABELS[t] ?? t).join('、') || '—'
}
function score(task: RevisitTask): string {
  const value = task.rationale.model_score
  return typeof value === 'number' ? value.toFixed(2) : '—'
}
</script>

<template>
  <SectionCard title="等人确认" :subtitle="tasks.length ? `${tasks.length} 株，按优先级` : '没有等人确认的株'" class="confirm-panel">
    <ul v-if="shown.length" class="list">
      <li v-for="task in shown" :key="task.id">
        <b class="key">{{ unitKey(task) }}</b>
        <StateTag v-if="taskState(task)" :state="taskState(task)!" size="small" />
        <span v-else class="muted">—</span>
        <span class="reason">{{ reasons(task) }}</span>
        <span class="score">模型分 <b>{{ score(task) }}</b></span>
      </li>
    </ul>
    <p v-if="rest" class="rest">另有 {{ rest }} 株，在「待确认」页处理</p>
    <p v-if="!tasks.length" class="none">模型推荐的株确认完了；新的推荐会随下一次巡检和计划出现。</p>
  </SectionCard>
</template>

<style scoped>
.confirm-panel :deep(.sc-body) { padding-top: var(--space-2); padding-bottom: var(--space-3); }
.list { list-style: none; margin: 0; padding: 0; }
.list li {
  display: grid;
  grid-template-columns: 6.5em auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  font-size: var(--fs-13);
  line-height: var(--lh-13);
}
.list li + li { border-top: 1px solid var(--border); }
.key { font-family: var(--font-mono); font-weight: var(--fw-medium); color: var(--text-primary); }
.reason { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-regular); }
.score { color: var(--text-secondary); white-space: nowrap; }
.score b { font-variant-numeric: tabular-nums; color: var(--text-primary); font-weight: var(--fw-medium); }
.rest, .none { margin: var(--space-2) 0 0; font-size: var(--fs-12); line-height: var(--lh-12); color: var(--text-secondary); }
.none { margin: 0; }
</style>
