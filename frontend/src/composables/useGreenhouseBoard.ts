/**
 * 工作台与展示屏共用的大棚概况（计划 0018）：逐个大棚调 0014/0015 的现有接口（环境、最近计划、每株状态、最近巡检），
 * 外加未完成的确认任务和最近巡检。2 个大棚 + 1 块大田约 21 个请求；棚多了再考虑设计 5 的汇总接口。
 */
import { computed, ref } from 'vue'
import { greenhouseApi, patrolsApi, softwareLoopApi } from '../api'
import { useFieldsStore } from '../stores/fields'
import {
  isGreenhouse,
  type EnvSummary, type Field, type Patrol, type PatrolPlan, type PlanListName, type PlantState, type PlantStateValue,
  type RevisitTask,
} from '../types'
import { fieldDate } from '../utils/fieldTime'

export interface GreenhouseCard {
  field: Field
  env: EnvSummary | null
  plan: PatrolPlan | null
  states: PlantState[]
  lastPatrol: Patrol | null
}

export interface OpenFieldCard {
  field: Field
  lastPatrol: Patrol | null
}

export const PLAN_LISTS: PlanListName[] = ['confirm', 'reshoot', 'coverage', 'random']
export const PLANT_STATES: PlantStateValue[] = ['healthy', 'early', 'symptomatic', 'unknown']

export function stateCounts(states: PlantState[]): Record<PlantStateValue, number> {
  const counts: Record<PlantStateValue, number> = { healthy: 0, early: 0, symptomatic: 0, unknown: 0 }
  for (const s of states) counts[s.state] += 1
  return counts
}

/** 最近一条温湿度读数的时间：接口在有读数时把 until 定在最新读数之后 1 秒，没有读数时为空 */
export function latestReadingAt(env: EnvSummary | null): number | null {
  if (!env || !env.sensors.length) return null
  return Date.parse(env.until) - 1000
}

/** 株状态最近一次变化的依据时间：最近拍到或最近人工确认，取较晚的 */
export function statesUpdatedAt(states: PlantState[]): number | null {
  let latest: number | null = null
  for (const s of states) {
    for (const at of [s.last_seen_at, s.reviewed_at]) {
      if (!at) continue
      const ms = Date.parse(at)
      if (latest == null || ms > latest) latest = ms
    }
  }
  return latest
}

export function useGreenhouseBoard(options: { recentLimit?: number } = {}) {
  const fieldsStore = useFieldsStore()

  const loading = ref(false)
  const loaded = ref(false)
  /** 最近一次成功加载的时刻（展示屏显示「数据更新于」） */
  const loadedAt = ref<number | null>(null)
  const cards = ref<GreenhouseCard[]>([])
  const openFields = ref<OpenFieldCard[]>([])
  const confirmTasks = ref<RevisitTask[]>([])
  const confirmCapped = ref(false)
  const recent = ref<Patrol[]>([])
  const today = ref(fieldDate())

  const lastPatrolOf = (fieldId: number) =>
    patrolsApi.list({ field_id: fieldId, limit: 1 }).then((page) => page.items[0] ?? null).catch(() => null)

  /** 拉一遍全部数据；失败时抛错并保留上一次的数据（展示屏自动刷新失败不清屏） */
  async function load(): Promise<void> {
    loading.value = true
    try {
      const fields = await fieldsStore.load(true)
      const [confirm, latest, greenhouses, others] = await Promise.all([
        softwareLoopApi.openTasks('label', { limit: 500 }),
        patrolsApi.list({ limit: options.recentLimit ?? 5 }),
        Promise.all(fields.filter((f) => isGreenhouse(f)).map(async (field): Promise<GreenhouseCard> => {
          const [env, plan, states, lastPatrol] = await Promise.all([
            greenhouseApi.env(field.id).catch(() => null),
            greenhouseApi.latestPlan(field.id).catch(() => null), // 404 = 还没生成过计划
            greenhouseApi.plantStates(field.id).catch(() => [] as PlantState[]),
            lastPatrolOf(field.id),
          ])
          return { field, env, plan, states, lastPatrol }
        })),
        Promise.all(fields.filter((f) => !isGreenhouse(f)).map(async (field) => ({ field, lastPatrol: await lastPatrolOf(field.id) }))),
      ])
      today.value = fieldDate()
      confirmTasks.value = confirm.tasks
      confirmCapped.value = confirm.capped
      recent.value = latest.items
      // 环境风险高的棚排前面；环境数据不足的排最后（不是低风险，只是没法比）
      cards.value = greenhouses.sort((a, b) =>
        (b.env?.index.env_index ?? -1) - (a.env?.index.env_index ?? -1) || a.field.name.localeCompare(b.field.name, 'zh-CN'))
      openFields.value = others
      loaded.value = true
      loadedAt.value = Date.now()
    } finally {
      loading.value = false
    }
  }

  const confirmByField = computed(() => {
    const counts = new Map<number, number>()
    for (const task of confirmTasks.value) counts.set(task.field_id, (counts.get(task.field_id) ?? 0) + 1)
    return counts
  })

  /** 只认今天的计划；最近一次计划是前几天的就当今日未生成 */
  function todayPlan(card: GreenhouseCard): PatrolPlan | null {
    return card.plan?.plan_date === today.value ? card.plan : null
  }

  return {
    loading, loaded, loadedAt, cards, openFields, confirmTasks, confirmCapped, recent, today,
    load, confirmByField, todayPlan,
  }
}
