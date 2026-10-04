/**
 * 按株取单株时间线的小缓存（待确认页用）：列表只取当前页的株，最多同时 4 个请求；
 * 取过的留着，侧滑面板直接用；确认之后 invalidate 再取。失败的株记下错误，不阻塞其他株。
 */
import { reactive } from 'vue'
import { observationUnitsApi } from '../api'
import { errMsg } from '../api/http'
import type { UnitTimeline } from '../types'

export interface TimelineEntry {
  data: UnitTimeline | null
  error: string
  loading: boolean
}

export function useTimelineCache(days = 30, concurrency = 4) {
  const entries = reactive(new Map<number, TimelineEntry>())
  const queue: number[] = []
  let active = 0

  function pump() {
    while (active < concurrency && queue.length) {
      const unitId = queue.shift()!
      const entry = entries.get(unitId)
      if (!entry) continue
      active += 1
      observationUnitsApi.timeline(unitId, days)
        .then((data) => { entry.data = data; entry.error = '' })
        .catch((e) => { entry.error = errMsg(e) })
        .finally(() => {
          entry.loading = false
          active -= 1
          pump()
        })
    }
  }

  /** 排队取一株；已取到或正在取的不重复取。urgent 插到队首（面板里正在看的那株） */
  function request(unitId: number, urgent = false) {
    const entry = entries.get(unitId)
    if (entry && (entry.loading || entry.data)) {
      if (urgent && entry.loading && queue.includes(unitId)) {
        queue.splice(queue.indexOf(unitId), 1)
        queue.unshift(unitId)
      }
      return
    }
    entries.set(unitId, { data: entry?.data ?? null, error: '', loading: true })
    if (urgent) queue.unshift(unitId)
    else queue.push(unitId)
    pump()
  }

  function get(unitId: number | null | undefined): TimelineEntry | undefined {
    return unitId == null ? undefined : entries.get(unitId)
  }

  /** 丢掉一株的缓存（确认后照片上多了人工结论），下次 request 重新取 */
  function invalidate(unitId: number) {
    const index = queue.indexOf(unitId)
    if (index >= 0) queue.splice(index, 1)
    entries.delete(unitId)
  }

  return { request, get, invalidate }
}
