/**
 * 大棚详情页的共享数据（计划 0018 阶段 B）：父页 FieldDetailView 建一份，各标签页注入。
 * 每类数据第一次用到时才拉，切标签不重复请求；页头「刷新」把已经拉过的全部重拉。失败时保留上一次的数据并记下错误。
 */
import { computed, inject, provide, ref, type InjectionKey, type Ref } from 'vue'
import { fieldsApi, greenhouseApi, patrolsApi, softwareLoopApi } from '../api'
import { errMsg, isNotFound } from '../api/http'
import { isGreenhouse, type EnvSummary, type Field, type Patrol, type PatrolPlan, type PlantState, type RevisitTask } from '../types'

export interface Resource<T> {
  data: Ref<T>
  error: Ref<string>
  loading: Ref<boolean>
  loaded: Ref<boolean>
  load: (force?: boolean) => Promise<void>
}

function resource<T>(fetch: () => Promise<T>, initial: T): Resource<T> {
  const data = ref(initial) as Ref<T>
  const error = ref('')
  const loading = ref(false)
  const loaded = ref(false)
  let pending: Promise<void> | null = null
  function load(force = false): Promise<void> {
    if (pending) return pending
    if (loaded.value && !force) return Promise.resolve()
    loading.value = true
    pending = fetch()
      .then((value) => {
        data.value = value
        error.value = ''
      })
      .catch((e) => { error.value = errMsg(e) })
      .finally(() => {
        loaded.value = true
        loading.value = false
        pending = null
      })
    return pending
  }
  return { data, error, loading, loaded, load }
}

/** 该地块最近的巡检（巡检记录标签页、概览共用） */
export const FIELD_PATROL_LIMIT = 100

export function createFieldDetail(fieldId: number) {
  const field = resource<Field | null>(() => fieldsApi.get(fieldId), null)
  const env = resource<EnvSummary | null>(() => greenhouseApi.env(fieldId), null)
  // 404 = 还没生成过计划，不算出错
  const plan = resource<PatrolPlan | null>(
    () => greenhouseApi.latestPlan(fieldId).catch((e) => { if (isNotFound(e)) return null; throw e }), null)
  const states = resource<PlantState[]>(() => greenhouseApi.plantStates(fieldId), [])
  const patrols = resource<{ items: Patrol[]; total: number }>(
    () => patrolsApi.list({ field_id: fieldId, limit: FIELD_PATROL_LIMIT }).then(({ items, total }) => ({ items, total })),
    { items: [], total: 0 })
  const confirm = resource<RevisitTask[]>(
    () => softwareLoopApi.openTasks('label', { field_id: fieldId }).then((r) => r.tasks), [])

  const all = [field, env, plan, states, patrols, confirm]
  const greenhouse = computed(() => isGreenhouse(field.data.value))
  const refreshing = computed(() => all.some((r) => r.loading.value))

  /** 页头「刷新」：已经拉过的全部重拉（没打开过的标签用到时再拉） */
  function refresh(): Promise<unknown> {
    return Promise.all(all.filter((r) => r.loaded.value).map((r) => r.load(true)))
  }

  return { fieldId, field, env, plan, states, patrols, confirm, greenhouse, refreshing, refresh }
}

export type FieldDetail = ReturnType<typeof createFieldDetail>

const KEY: InjectionKey<FieldDetail> = Symbol('field-detail')

export function provideFieldDetail(fieldId: number): FieldDetail {
  const detail = createFieldDetail(fieldId)
  provide(KEY, detail)
  return detail
}

export function useFieldDetail(): FieldDetail {
  const detail = inject(KEY)
  if (!detail) throw new Error('useFieldDetail 只能在大棚详情页的标签页里用')
  return detail
}
