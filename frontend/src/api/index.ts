/** 资源客户端：每个后端资源一组类型化方法。 */
import { request } from './http'
import type { Crop, Device, Field, Planting } from '../types'

export interface FieldCreatePayload {
  name: string
  boundary: Field['boundary']
  area_ha?: number | null
  soil_type?: string | null
  notes?: string | null
}
export type FieldUpdatePayload = Partial<FieldCreatePayload>

export interface CropCreatePayload {
  name: string
  variety?: string | null
  lifecycle_days: number
  stages: { name: string; days: number }[]
  description?: string | null
}
export type CropUpdatePayload = Partial<CropCreatePayload>

export interface DeviceCreatePayload {
  code: string
  name: string
  type: Device['type']
  model?: string | null
  status?: Device['status']
  notes?: string | null
}
export type DeviceUpdatePayload = Partial<Omit<DeviceCreatePayload, 'code'>>

export interface PlantingCreatePayload {
  field_id: number
  crop_id: number
  sowing_date: string
  expected_harvest_date?: string | null
  status?: Planting['status']
  notes?: string | null
}
export type PlantingUpdatePayload = Partial<
  Omit<PlantingCreatePayload, 'field_id' | 'crop_id'>
>

export const fieldsApi = {
  list: () => request<Field[]>('/fields'),
  create: (payload: FieldCreatePayload) =>
    request<Field>('/fields', { method: 'POST', body: payload }),
  update: (id: number, payload: FieldUpdatePayload) =>
    request<Field>(`/fields/${id}`, { method: 'PATCH', body: payload }),
  remove: (id: number) => request<void>(`/fields/${id}`, { method: 'DELETE' }),
}

export const cropsApi = {
  list: () => request<Crop[]>('/crops'),
  create: (payload: CropCreatePayload) =>
    request<Crop>('/crops', { method: 'POST', body: payload }),
  update: (id: number, payload: CropUpdatePayload) =>
    request<Crop>(`/crops/${id}`, { method: 'PATCH', body: payload }),
  remove: (id: number) => request<void>(`/crops/${id}`, { method: 'DELETE' }),
}

export const devicesApi = {
  list: () => request<Device[]>('/devices'),
  create: (payload: DeviceCreatePayload) =>
    request<Device>('/devices', { method: 'POST', body: payload }),
  update: (id: number, payload: DeviceUpdatePayload) =>
    request<Device>(`/devices/${id}`, { method: 'PATCH', body: payload }),
  remove: (id: number) => request<void>(`/devices/${id}`, { method: 'DELETE' }),
}

export const plantingsApi = {
  list: (params: { field_id?: number; crop_id?: number; status?: string } = {}) => {
    const qs = new URLSearchParams()
    if (params.field_id != null) qs.set('field_id', String(params.field_id))
    if (params.crop_id != null) qs.set('crop_id', String(params.crop_id))
    if (params.status) qs.set('status', params.status)
    const q = qs.toString()
    return request<Planting[]>(`/plantings${q ? `?${q}` : ''}`)
  },
  create: (payload: PlantingCreatePayload) =>
    request<Planting>('/plantings', { method: 'POST', body: payload }),
  update: (id: number, payload: PlantingUpdatePayload) =>
    request<Planting>(`/plantings/${id}`, { method: 'PATCH', body: payload }),
  remove: (id: number) => request<void>(`/plantings/${id}`, { method: 'DELETE' }),
}
