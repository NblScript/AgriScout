/** 与后端 schemas 对齐的领域类型（单一事实源：backend/app/schemas/）。 */

export interface StageItem {
  name: string
  days: number
}

export interface GeoJSONPolygon {
  type: 'Polygon'
  coordinates: number[][][]
}

export interface Field {
  id: number
  name: string
  boundary: GeoJSONPolygon
  area_ha: number | null
  soil_type: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface Crop {
  id: number
  name: string
  variety: string | null
  lifecycle_days: number
  stages: StageItem[]
  default_rules: Record<string, unknown>[] | null
  description: string | null
  created_at: string
  updated_at: string
}

export type DeviceType = 'rover' | 'drone' | 'station'
export type DeviceStatus = 'idle' | 'active' | 'maintenance' | 'offline'

export interface Device {
  id: number
  code: string
  name: string
  type: DeviceType
  model: string | null
  status: DeviceStatus
  notes: string | null
  created_at: string
  updated_at: string
}

export type PlantingStatus = 'active' | 'harvested' | 'archived'

export interface Planting {
  id: number
  field_id: number
  crop_id: number
  field_name: string | null
  crop_name: string | null
  sowing_date: string
  expected_harvest_date: string | null
  status: PlantingStatus
  notes: string | null
  created_at: string
  updated_at: string
}

/** 展示用中文字典 */
export const DEVICE_TYPE_LABELS: Record<DeviceType, string> = {
  rover: '巡检小车',
  drone: '无人机',
  station: '固定监测点',
}

export const DEVICE_STATUS_LABELS: Record<DeviceStatus, string> = {
  idle: '空闲',
  active: '作业中',
  maintenance: '维护中',
  offline: '离线',
}

export const PLANTING_STATUS_LABELS: Record<PlantingStatus, string> = {
  active: '生长期',
  harvested: '已收获',
  archived: '已归档',
}
