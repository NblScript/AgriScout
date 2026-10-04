<script setup lang="ts">
/**
 * 等人确认卡（展示屏、大棚详情概览共用）：本棚未完成的「确认」任务前几条（按优先级），株号、当前状态、原因、模型分。
 * navigable 时株号可点进单株时间线，moreTo 给右上角「去确认」入口；展示屏只看不点。
 */
import { computed } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import SectionCard from './ui/SectionCard.vue'
import StateTag from './ui/StateTag.vue'
import type { RevisitTask } from '../types'
import { taskModelScore, taskPlantState, taskReasons, taskUnitKey } from '../utils/planTask'

const props = withDefaults(defineProps<{ tasks: RevisitTask[]; limit?: number; navigable?: boolean; moreTo?: string }>(), {
  limit: 5,
  navigable: false,
  moreTo: undefined,
})

const shown = computed(() => props.tasks.slice(0, props.limit))
const rest = computed(() => Math.max(props.tasks.length - props.limit, 0))
</script>

<template>
  <SectionCard title="等人确认" :subtitle="tasks.length ? `${tasks.length} 株，按优先级` : '没有等人确认的株'" class="confirm-panel">
    <template v-if="moreTo && tasks.length" #actions>
      <router-link :to="moreTo" class="more">去确认<el-icon><ArrowRight /></el-icon></router-link>
    </template>
    <ul v-if="shown.length" class="list">
      <li v-for="task in shown" :key="task.id">
        <router-link v-if="navigable && task.observation_unit_id" :to="`/units/${task.observation_unit_id}`" class="key">
          {{ taskUnitKey(task) }}
        </router-link>
        <b v-else class="key">{{ taskUnitKey(task) }}</b>
        <StateTag v-if="taskPlantState(task)" :state="taskPlantState(task)!" size="small" />
        <span v-else class="muted">—</span>
        <span class="reason">{{ taskReasons(task).join('、') || '—' }}</span>
        <span class="score">模型分 <b>{{ taskModelScore(task) }}</b></span>
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
a.key { color: var(--el-color-primary); }
.reason { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-regular); }
.score { color: var(--text-secondary); white-space: nowrap; }
.score b { font-variant-numeric: tabular-nums; color: var(--text-primary); font-weight: var(--fw-medium); }
.rest, .none { margin: var(--space-2) 0 0; font-size: var(--fs-12); line-height: var(--lh-12); color: var(--text-secondary); }
.none { margin: 0; }
.more { display: inline-flex; align-items: center; gap: 2px; font-size: var(--fs-13); }
</style>
