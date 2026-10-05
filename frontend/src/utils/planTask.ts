/** 巡检计划写出的任务（RevisitTask）里常用的字段：株号、计划时的株状态、触发原因、模型分（工作台、待确认、大棚详情、展示屏共用）。 */
import { PLAN_TRIGGER_LABELS, PLANT_STATE_LABELS, type PlantStateValue, type RevisitTask } from '../types'

export function taskUnitKey(task: RevisitTask): string {
  return (task.parameters.observation_key as string | undefined) ?? `任务 #${task.id}`
}

/** 生成计划时这株的状态（rationale.state） */
export function taskPlantState(task: RevisitTask): PlantStateValue | null {
  const state = task.rationale.state as PlantStateValue | undefined
  return state && state in PLANT_STATE_LABELS ? state : null
}

export function taskReasons(task: RevisitTask): string[] {
  return ((task.rationale.triggers as string[] | undefined) ?? []).map((t) => PLAN_TRIGGER_LABELS[t] ?? t)
}

export function taskModelScore(task: RevisitTask): string {
  const score = task.rationale.model_score
  return typeof score === 'number' ? score.toFixed(2) : '—'
}
