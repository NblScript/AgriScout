/** 统一 fetch 封装：JSON 编解码、错误信息提取。 */

const BASE = '/api/v1'

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const resp = await fetch(BASE + path, {
    method: opts.method ?? 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  })
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
    throw new Error(detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

/** 统一错误文案提取：全站 ElMessage.error(errMsg(e)) 一处收口。 */
export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
