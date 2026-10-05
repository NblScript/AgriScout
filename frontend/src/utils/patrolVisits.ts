/** 巡检回放大棚模式：把一次巡检的采样点按株归组（同一株的正面、叶背、补拍放一组），按第一次拍到的顺序排。 */
import type { CapturePointFull } from '../types'

export interface PlantVisit {
  /** 'u{株 id}'，没关联到株的点为 'p{点 id}' */
  key: string
  unitId: number | null
  label: string
  points: CapturePointFull[]
}

export function groupVisits(points: CapturePointFull[]): PlantVisit[] {
  const visits: PlantVisit[] = []
  const byUnit = new Map<number, PlantVisit>()
  const ordered = [...points].sort((a, b) => a.seq - b.seq)
  for (const point of ordered) {
    const unitId = point.observation_unit_id
    const existing = unitId != null ? byUnit.get(unitId) : undefined
    if (existing) {
      existing.points.push(point)
      continue
    }
    const visit: PlantVisit = {
      key: unitId != null ? `u${unitId}` : `p${point.id}`,
      unitId,
      label: point.observation_key ?? (unitId != null ? `株 #${unitId}` : `采样点 #${point.seq}`),
      points: [point],
    }
    if (unitId != null) byUnit.set(unitId, visit)
    visits.push(visit)
  }
  return visits
}
