/** 车端出车时的时钟状态（计划 0007 P0-2，D26）读成一句话，与 rover/clock.py 的 describe 同口径。 */
import type { ClockStatus } from '../types'

const SYNCED_TEXT = { true: '已对时', false: '未对时', null: '对时状态未知' } as const

/** 「约 3 小时 5 分」这类说法，与平台告警（services/clock_check.py）同口径 */
function span(seconds: number): string {
  seconds = Math.abs(seconds)
  if (seconds < 90) return `${Math.round(seconds)} 秒`
  const totalMinutes = Math.round(seconds / 60)
  if (totalMinutes < 90) return `约 ${totalMinutes} 分钟`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours < 48) return `约 ${hours} 小时${minutes ? ` ${minutes} 分` : ''}`
  const days = Math.round(hours / 24)
  return days < 730 ? `约 ${days} 天` : `约 ${Math.round(days / 365.25)} 年`
}

/** 只说对时状态：「未对时（chrony）」 */
export function describeSync(clock: ClockStatus): string {
  const synced = SYNCED_TEXT[String(clock.synced) as keyof typeof SYNCED_TEXT]
  return clock.source === 'unknown' ? synced : `${synced}（${clock.source}）`
}

/** 对时状态加与平台的时间差：「已对时（chrony），与平台差 +0.4 秒」 */
export function describeClock(clock: ClockStatus): string {
  const text = describeSync(clock)
  const offset = clock.offset_s
  if (offset == null) return `${text}，出车时没和平台对表`
  if (Math.abs(offset) >= 90) return `${text}，比平台${offset > 0 ? '快' : '慢'} ${span(offset)}`
  const rounded = Math.round(offset * 10) / 10
  return `${text}，与平台差 ${rounded < 0 ? '−' : '+'}${Math.abs(rounded).toFixed(1)} 秒`
}
