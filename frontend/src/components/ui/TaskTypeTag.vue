<script setup lang="ts">
/** 任务类型标签：颜色取令牌 --task-*，色块描边线型与网格一致（确认实线、补拍虚线、全覆盖点线、抽查双线）。 */
import { computed } from 'vue'
import { PLAN_LIST_LABELS, PLAN_LIST_SHORT_LABELS, TASK_TYPE_LIST, type PlanListName, type RevisitTask } from '../../types'

const props = withDefaults(defineProps<{
  type: PlanListName | RevisitTask['task_type']
  /** 长名（推给人确认 / 叶背补拍 …），缺省用短名 */
  long?: boolean
  count?: number | null
}>(), { long: false, count: null })

const list = computed<PlanListName>(() =>
  props.type in PLAN_LIST_LABELS ? (props.type as PlanListName) : TASK_TYPE_LIST[props.type as RevisitTask['task_type']])
const text = computed(() => (props.long ? PLAN_LIST_LABELS : PLAN_LIST_SHORT_LABELS)[list.value])
</script>

<template>
  <span class="task-tag" :class="`is-${list}`">
    <i class="swatch" aria-hidden="true" />
    {{ text }}<b v-if="count != null" class="count">{{ count }}</b>
  </span>
</template>

<style scoped>
.task-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-soft);
  color: var(--c-ink);
  font-size: var(--fs-12);
  font-weight: var(--fw-medium);
  line-height: 1;
  white-space: nowrap;
}
.is-confirm { --c-base: var(--task-confirm); --c-ink: var(--task-confirm-ink); --c-soft: var(--task-confirm-soft); --c-line: var(--task-confirm-line); }
.is-reshoot { --c-base: var(--task-reshoot); --c-ink: var(--task-reshoot-ink); --c-soft: var(--task-reshoot-soft); --c-line: var(--task-reshoot-line); }
.is-coverage { --c-base: var(--task-coverage); --c-ink: var(--task-coverage-ink); --c-soft: var(--task-coverage-soft); --c-line: var(--task-coverage-line); }
.is-random { --c-base: var(--task-random); --c-ink: var(--task-random-ink); --c-soft: var(--task-random-soft); --c-line: var(--task-random-line); }
.swatch {
  flex: none;
  width: 12px;
  height: 10px;
  border-radius: 2px;
  border: 2px var(--c-line) var(--c-base);
  background: var(--bg-card);
}
.is-random .swatch { border-width: 3px; }
.count { font-weight: var(--fw-semibold); font-variant-numeric: tabular-nums; margin-left: 2px; }
</style>
