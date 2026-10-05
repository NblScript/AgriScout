/**
 * 田间时区（UTC+8，与后端 core/timeutil.field_date 同口径）的日期与时刻：不随浏览器时区漂移，
 * 外地评审打开页面看到的仍是棚里的时间。
 */
const OFFSET_MS = 8 * 3600 * 1000
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

type Instant = string | number | Date

function shifted(at: Instant): Date {
  const ms = typeof at === 'string' ? Date.parse(at) : at instanceof Date ? at.getTime() : at
  return new Date(ms + OFFSET_MS)
}

const pad = (n: number) => String(n).padStart(2, '0')

/** 田间日期 YYYY-MM-DD */
export function fieldDate(at: Instant = Date.now()): string {
  return shifted(at).toISOString().slice(0, 10)
}

/** 月/日、时、分 */
export function fieldParts(at: Instant): { day: string; hour: number; minute: number } {
  const d = shifted(at)
  return { day: `${pad(d.getUTCMonth() + 1)}/${pad(d.getUTCDate())}`, hour: d.getUTCHours(), minute: d.getUTCMinutes() }
}

/** 「MM/DD HH:mm」；空值显示 — */
export function fieldClock(at: Instant | null | undefined): string {
  if (at == null || at === '') return '—'
  const { day, hour, minute } = fieldParts(at)
  return `${day} ${pad(hour)}:${pad(minute)}`
}

/** 「HH:mm」 */
export function fieldHm(at: Instant): string {
  const { hour, minute } = fieldParts(at)
  return `${pad(hour)}:${pad(minute)}`
}

/** 田间日期（YYYY-MM-DD，如时间线的 field_date）→「10/03 星期五」 */
export function fieldDayLabel(date: string): string {
  const d = new Date(`${date}T00:00:00Z`)
  return `${pad(d.getUTCMonth() + 1)}/${pad(d.getUTCDate())} 星期${WEEKDAYS[d.getUTCDay()]}`
}

/** 「HH:mm:ss」（展示屏时钟） */
export function fieldTimeHms(at: Instant = Date.now()): string {
  const d = shifted(at)
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
}

/** 「2026-10-03 星期六」 */
export function fieldDateLabel(at: Instant = Date.now()): string {
  const d = shifted(at)
  return `${d.toISOString().slice(0, 10)} 星期${WEEKDAYS[d.getUTCDay()]}`
}

/** 「刚刚 / 12 分钟前 / 3 小时前 / 2 天前」，一周以上给日期时刻 */
export function relativeTime(at: Instant | null | undefined, now: number = Date.now()): string {
  if (at == null || at === '') return '—'
  const ms = typeof at === 'string' ? Date.parse(at) : at instanceof Date ? at.getTime() : at
  const minutes = Math.floor((now - ms) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} 小时前`
  if (minutes < 7 * 24 * 60) return `${Math.floor(minutes / 1440)} 天前`
  return fieldClock(ms)
}
