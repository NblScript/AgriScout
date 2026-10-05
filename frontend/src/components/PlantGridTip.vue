<script setup lang="ts">
/** PlantGrid 的悬停提示：挂在 body 上（不受网格容器滚动裁切），显示株号、状态、来源、模型分、上次叶背、今日任务与原因。 */
import StateTag from './ui/StateTag.vue'
import TaskTypeTag from './ui/TaskTypeTag.vue'
import { PLAN_TRIGGER_LABELS, PLANT_SOURCE_LABELS, TASK_STATUS_LABELS, type PlanItem, type PlantState } from '../types'
import { fieldClock } from '../utils/fieldTime'

defineProps<{
  plant: PlantState
  task: PlanItem | null
  /** 视口坐标：x 为提示框水平中心，y 为贴着格子的那条边 */
  x: number
  y: number
  /** 格子靠近视口顶部时提示框放到格子下方 */
  below: boolean
  navigable: boolean
}>()

function underText(p: PlantState): string {
  if (p.last_under_accepted === false) return '不合格，需要补拍'
  if (p.last_under_ok_at) return `合格 · ${fieldClock(p.last_under_ok_at)}`
  return '还没拍到合格叶背'
}
function reasons(item: PlanItem): string {
  const triggers = (item.rationale.triggers as string[] | undefined) ?? []
  return triggers.map((t) => PLAN_TRIGGER_LABELS[t] ?? t).join('、')
}
</script>

<template>
  <Teleport to="body">
    <div class="pg-tip" :class="{ below }" :style="{ left: `${x}px`, top: `${y}px` }" role="tooltip">
      <div class="head">
        <b class="key">{{ plant.key }}</b>
        <StateTag :state="plant.state" size="small" />
      </div>
      <dl>
        <dt>来源</dt><dd>{{ PLANT_SOURCE_LABELS[plant.source] }}</dd>
        <template v-if="plant.model_score != null"><dt>模型分</dt><dd class="tabular">{{ plant.model_score.toFixed(2) }}</dd></template>
        <dt>上次叶背</dt><dd>{{ underText(plant) }}</dd>
        <template v-if="task">
          <dt>今日任务</dt>
          <dd><TaskTypeTag :type="task.list_name" /> {{ TASK_STATUS_LABELS[task.task_status] ?? task.task_status }}</dd>
          <template v-if="reasons(task)"><dt>原因</dt><dd>{{ reasons(task) }}</dd></template>
        </template>
      </dl>
      <p v-if="navigable" class="foot">点击查看单株时间线</p>
    </div>
  </Teleport>
</template>

<style scoped>
.pg-tip {
  position: fixed;
  z-index: 3000;
  width: 260px;
  padding: var(--space-3);
  transform: translate(-50%, -100%);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-2);
  pointer-events: none;
  font-size: var(--fs-13);
  line-height: var(--lh-13);
  color: var(--text-regular);
}
.pg-tip.below { transform: translate(-50%, 0); }
.head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-bottom: var(--space-2); }
.key { font-family: var(--font-mono); font-size: var(--fs-14); color: var(--text-primary); }
dl { display: grid; grid-template-columns: auto 1fr; gap: 4px var(--space-3); margin: 0; }
dt { color: var(--text-secondary); white-space: nowrap; }
dd { margin: 0; color: var(--text-primary); }
.foot { margin: var(--space-2) 0 0; font-size: var(--fs-12); color: var(--text-secondary); }
</style>
