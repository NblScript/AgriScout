/** 统一 fetch 封装：JSON 编解码、登录令牌、错误信息提取。 */
import type { Page } from '../types'

const BASE = '/api/v1'

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
}

/* 令牌与 401 处理由 auth store 注入（避免 http ↔ store 循环依赖）。 */
let authToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

/** 带 HTTP 状态码的错误（如 404 = 还没生成过计划，调用方据此区分「没有」和「出错」） */
export class HttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'HttpError'
  }
}

export function isNotFound(e: unknown): boolean {
  return e instanceof HttpError && e.status === 404
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  const resp = await fetch(BASE + path, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  })
  // 令牌失效（过期/账号停用）：清登录态并回登录页；登录接口自己的 401 是「口令错」，不跳转
  if (resp.status === 401 && path !== '/auth/login') onUnauthorized?.()
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const data = (await resp.json()) as { detail?: unknown }
      detail =
        typeof data.detail === 'string'
          ? data.detail
          : Array.isArray(data.detail)
            ? (data.detail as { msg?: string }[]).map((d) => d.msg ?? '').join('；') || detail
            : JSON.stringify(data.detail ?? data)
    } catch {
      /* 保留 HTTP 状态码信息 */
    }
    throw new HttpError(detail, resp.status)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

/**
 * 拉取分页接口的全部数据：total 超过单页上限时逐页请求。
 * 单次请求有 limit 上限（采样点 2000、建议 500），2600 点巡检或 ~170 点以上的建议列表
 * 会被静默截断，地图和建议面板只显示前一部分。
 */
export async function requestAllPages<T>(path: string, pageSize: number): Promise<Page<T>> {
  const sep = path.includes('?') ? '&' : '?'
  const items: T[] = []
  let total = 0
  do {
    const page = await request<Page<T>>(`${path}${sep}skip=${items.length}&limit=${pageSize}`)
    items.push(...page.items)
    total = page.total
    if (page.items.length === 0) break
  } while (items.length < total)
  return { items, total, skip: 0, limit: items.length }
}

/** 统一错误文案提取：全站 ElMessage.error(errMsg(e)) 一处收口。 */
export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
