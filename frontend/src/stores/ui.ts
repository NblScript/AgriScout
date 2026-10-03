import { defineStore } from 'pinia'
import { ref } from 'vue'
import { softwareLoopApi } from '../api'

/** 面包屑的一段；没有 to 的是当前页 */
export interface Crumb {
  label: string
  to?: string
}

const FIELD_KEY = 'agriscout_current_field'
const SIDEBAR_KEY = 'agriscout_sidebar_collapsed'

function readNumber(key: string): number | null {
  try {
    const value = Number(localStorage.getItem(key))
    return Number.isInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

function write(key: string, value: string | null) {
  try {
    if (value == null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch { /* 隐私模式等存储不可用：只在本页会话内记住 */ }
}

/**
 * 界面全局状态（计划 0018）：侧栏折叠、手机端侧栏抽屉、当前地块（记住上次选择）、
 * 页面自报的面包屑、待确认数角标。
 */
export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(readNumber(SIDEBAR_KEY) === 1)
  const mobileNavOpen = ref(false)
  const currentFieldId = ref<number | null>(readNumber(FIELD_KEY))
  /** 页面通过 useBreadcrumb 设置；为空时顶栏按导航归属和路由标题显示 */
  const trail = ref<Crumb[]>([])
  let trailOwner = 0

  function setTrail(crumbs: Crumb[], owner: number) {
    trail.value = crumbs
    trailOwner = owner
  }

  /** 只清自己设的那份：新页面可能已经先设上了 */
  function clearTrail(owner: number) {
    if (trailOwner !== owner) return
    trail.value = []
    trailOwner = 0
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
    write(SIDEBAR_KEY, sidebarCollapsed.value ? '1' : null)
  }

  function setCurrentField(id: number | null) {
    currentFieldId.value = id
    write(FIELD_KEY, id == null ? null : String(id))
  }

  /* ---------- 待确认数：未完成（排队 / 已派 / 执行中）的 label 任务 ---------- */
  const confirmCount = ref<number | null>(null)
  const confirmCapped = ref(false)
  let lastRefresh = 0
  let inflight: Promise<void> | null = null

  /** force=false 时 15 秒内不重复请求（路由切换会频繁调用） */
  function refreshConfirmCount(force = false): Promise<void> {
    if (inflight) return inflight
    if (!force && Date.now() - lastRefresh < 15_000) return Promise.resolve()
    lastRefresh = Date.now()
    inflight = softwareLoopApi.openTasks('label', { limit: 500 })
      .then(({ tasks, capped }) => {
        confirmCount.value = tasks.length
        confirmCapped.value = capped
      })
      .catch(() => { /* 角标拿不到不影响页面；401 由全局处理 */ })
      .finally(() => { inflight = null })
    return inflight
  }

  return {
    sidebarCollapsed, mobileNavOpen, currentFieldId, trail, confirmCount, confirmCapped,
    toggleSidebar, setCurrentField, setTrail, clearTrail, refreshConfirmCount,
  }
})
