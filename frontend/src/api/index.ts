/** 资源客户端：每个后端资源一组类型化方法。 */
import { request, requestAllPages } from './http'
import type {
  AgentChatResult,
  Advice,
  AdviceStatus,
  AnalysisSummary,
  Annotation,
  AnnotationLabel,
  AnnotationSummary,
  CapturePointFull,
  Crop,
  Device,
  DeviceEvent,
  DeviceHeartbeat,
  EnvSummary,
  FacilityType,
  Field,
  ObservationUnit,
  Page,
  Patrol,
  PatrolDetail,
  PatrolPlan,
  PlantState,
  Planting,
  PatrolReport,
  RuleRevision,
  RiskPrediction,
  RevisitTask,
  DatasetVersion,
  ModelEvaluation,
  StatsOverview,
  LoginResult,
  UnitSource,
  UnitStatus,
  UnitTimeline,
  User,
  UserRole,
} from '../types'

export interface FieldCreatePayload {
  name: string
  boundary: Field['boundary']
  area_ha?: number | null
  soil_type?: string | null
  notes?: string | null
  facility_type?: FacilityType | null
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
  get: (id: number) => request<Field>(`/fields/${id}`),
  create: (payload: FieldCreatePayload) =>
    request<Field>('/fields', { method: 'POST', body: payload }),
  update: (id: number, payload: FieldUpdatePayload) =>
    request<Field>(`/fields/${id}`, { method: 'PATCH', body: payload }),
  remove: (id: number) => request<void>(`/fields/${id}`, { method: 'DELETE' }),
}

export interface UnitBulkRow {
  row_no: number
  plants: number
  spacing_m: number
  start_chainage_m?: number
}
export const observationUnitsApi = {
  list: (fieldId: number, params: { row_no?: number; status?: UnitStatus; created_from?: UnitSource } = {}) => {
    const qs = new URLSearchParams()
    if (params.row_no != null) qs.set('row_no', String(params.row_no))
    if (params.status) qs.set('status', params.status)
    if (params.created_from) qs.set('created_from', params.created_from)
    const q = qs.toString()
    return request<ObservationUnit[]>(`/fields/${fieldId}/observation-units${q ? `?${q}` : ''}`)
  },
  create: (fieldId: number, payload: { key: string; chainage_m?: number | null; tag_code?: string | null; note?: string | null }) =>
    request<ObservationUnit>(`/fields/${fieldId}/observation-units`, { method: 'POST', body: payload }),
  bulk: (fieldId: number, rows: UnitBulkRow[]) =>
    request<{ created: number; skipped: number }>(`/fields/${fieldId}/observation-units/bulk`, {
      method: 'POST',
      body: { rows },
    }),
  update: (id: number, payload: { tag_code?: string | null; status?: UnitStatus; note?: string | null }) =>
    request<ObservationUnit>(`/observation-units/${id}`, { method: 'PATCH', body: payload }),
  timeline: (id: number, days = 30) => request<UnitTimeline>(`/observation-units/${id}/timeline?days=${days}`),
}

export const greenhouseApi = {
  env: (fieldId: number, params: { since?: string; until?: string; sensor_key?: string } = {}) => {
    const qs = new URLSearchParams()
    if (params.since) qs.set('since', params.since)
    if (params.until) qs.set('until', params.until)
    if (params.sensor_key) qs.set('sensor_key', params.sensor_key)
    const q = qs.toString()
    return request<EnvSummary>(`/fields/${fieldId}/env${q ? `?${q}` : ''}`)
  },
  plantStates: (fieldId: number) => request<PlantState[]>(`/fields/${fieldId}/plant-states`),
  generatePlan: (fieldId: number, payload: { plan_date?: string; created_by: string; overrides?: Record<string, number> }) =>
    request<PatrolPlan>(`/fields/${fieldId}/patrol-plans`, { method: 'POST', body: payload }),
  latestPlan: (fieldId: number) => request<PatrolPlan>(`/fields/${fieldId}/patrol-plans/latest`),
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

export const deviceProtocolApi = {
  register: (payload: DeviceCreatePayload) =>
    request<Device>('/devices/register', { method: 'POST', body: payload }),
  heartbeat: (deviceId: number, payload: Record<string, unknown>) =>
    request<DeviceHeartbeat>(`/devices/${deviceId}/heartbeat`, { method: 'POST', body: payload }),
  heartbeats: (deviceId: number, limit = 100) =>
    request<DeviceHeartbeat[]>(`/devices/${deviceId}/heartbeats?limit=${limit}`),
  events: (deviceId: number, limit = 100) =>
    request<DeviceEvent[]>(`/devices/${deviceId}/events?limit=${limit}`),
  injectFault: (deviceId: number, payload: Record<string, unknown>) =>
    request<DeviceEvent>(`/devices/${deviceId}/fault-injection`, { method: 'POST', body: payload }),
  nextTask: (deviceId: number) =>
    request<RevisitTask | null>(`/devices/${deviceId}/tasks/next`),
  reportTaskStatus: (taskId: number, payload: { status: string; result_note?: string }) =>
    request<RevisitTask>(`/revisit-tasks/${taskId}`, { method: 'PATCH', body: payload }),
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

/* ---------- 巡检 / 采样点 / 建议（M6 可视化） ---------- */

export const patrolsApi = {
  list: (params: { field_id?: number; status?: string; analysis_status?: string } = {}) => {
    const qs = new URLSearchParams()
    if (params.field_id != null) qs.set('field_id', String(params.field_id))
    if (params.status) qs.set('status', params.status)
    if (params.analysis_status) qs.set('analysis_status', params.analysis_status)
    const q = qs.toString()
    return request<Page<Patrol>>(`/patrols${q ? `?${q}` : ''}`)
  },
  get: (id: number) => request<PatrolDetail>(`/patrols/${id}`),
  summary: (id: number) => request<AnalysisSummary>(`/patrols/${id}/analysis-summary`),
  analyze: (id: number) =>
    request<{ status: string; patrol_id: number }>(`/patrols/${id}/analyze`, { method: 'POST' }),
}

export const capturePointsApi = {
  listByPatrol: (patrolId: number) =>
    requestAllPages<CapturePointFull>(`/capture-points?patrol_id=${patrolId}`, 2000),
}

export const advicesApi = {
  list: (
    patrolId: number,
    params: { status?: string; capture_point_id?: number } = {},
  ) => {
    const qs = new URLSearchParams()
    if (params.status) qs.set('status', params.status)
    if (params.capture_point_id != null)
      qs.set('capture_point_id', String(params.capture_point_id))
    const query = qs.toString()
    return requestAllPages<Advice>(`/patrols/${patrolId}/advices${query ? `?${query}` : ''}`, 500)
  },
  setStatus: (adviceId: number, status: AdviceStatus) =>
    request<Advice>(`/advices/${adviceId}`, { method: 'PATCH', body: { status } }),
  generate: (patrolId: number) =>
    request<{ created: number; skipped_decided: number }>(
      `/patrols/${patrolId}/advices/generate`,
      { method: 'POST' },
    ),
}

/* ---------- 标注回流（M6+ 人工复核） ---------- */

export interface AnnotationSubmitPayload {
  label: AnnotationLabel
  annotator_name: string
  note?: string | null
}

export const annotationsApi = {  /** 同点同标签为更新（返回 200），否则新建（201） */
  submit: (pointId: number, payload: AnnotationSubmitPayload) =>
    request<Annotation>(`/capture-points/${pointId}/annotations`, {
      method: 'POST',
      body: payload,
    }),
  listByPoint: (pointId: number) =>
    request<Annotation[]>(`/capture-points/${pointId}/annotations`),
  summary: (patrolId: number) =>
    request<AnnotationSummary>(`/patrols/${patrolId}/annotations/summary`),
  remove: (annotationId: number) =>
    request<void>(`/annotations/${annotationId}`, { method: 'DELETE' }),
}

/* ---------- 规则线 L1：规则修订审批 ---------- */

export const ruleRevisionApi = {
  list: (status?: string) =>
    request<RuleRevision[]>(
      `/rule-revisions${status ? `?status=${status}` : ''}`,
    ),
  generate: () =>
    request<{ created: number; revision_ids: number[] }>('/rule-revisions/generate', {
      method: 'POST',
    }),
  shadow: (id: number) =>
    request<RuleRevision>(`/rule-revisions/${id}/shadow`, { method: 'POST' }),
  decide: (
    id: number,
    action: 'approve' | 'reject',
    payload: { decided_by: string; note?: string | null },
  ) =>
    request<RuleRevision>(`/rule-revisions/${id}/${action}`, {
      method: 'POST',
      body: payload,
    }),
}

/* ---------- 建议线 L2：诊断 Agent ---------- */

export const agentApi = {
  chat: (question: string, patrolId?: number) =>
    request<AgentChatResult>('/agent/chat', {
      method: 'POST',
      body: { question, patrol_id: patrolId ?? null },
    }),
}

/* ---------- 建议线 L1：巡检 AI 农事报告 ---------- */

export const reportsApi = {
  get: (patrolId: number) => request<PatrolReport>(`/patrols/${patrolId}/report`),
  generate: (patrolId: number) =>
    request<{ patrol_id: number; report_id: number; model: string; prompt_version: string }>(
      `/patrols/${patrolId}/report/generate`,
      { method: 'POST' },
    ),
}

/* ---------- 指挥大屏（平台聚合统计） ---------- */

export const statsApi = {
  overview: () => request<StatsOverview>('/stats/overview'),
}

/* ---------- 研究软件闭环：风险、复巡、数据集和模型闸门 ---------- */
export const softwareLoopApi = {
  predictions: (patrolId: number) =>
    request<RiskPrediction[]>(`/patrols/${patrolId}/risk-predictions`),
  generatePredictions: (patrolId: number, targetEvent = '目标病害首次显症') =>
    request<RiskPrediction[]>(`/patrols/${patrolId}/risk-predictions/generate`, {
      method: 'POST', body: { target_event: targetEvent, forecast_hours: 48 },
    }),
  followUp: (predictionId: number, payload: {
    status: string; reviewed_by: string; event_confirmed?: boolean; evidence?: Record<string, unknown>; note?: string
  }) => request(`/risk-predictions/${predictionId}/follow-up`, { method: 'POST', body: payload }),
  tasks: (fieldId?: number) => request<RevisitTask[]>(`/revisit-tasks${fieldId ? `?field_id=${fieldId}` : ''}`),
  generateTasks: (fieldId: number, patrolId: number, limit = 20) =>
    request<RevisitTask[]>('/revisit-tasks/generate', {
      method: 'POST', body: { field_id: fieldId, patrol_id: patrolId, limit },
    }),
  updateTask: (taskId: number, payload: { status?: string; result_note?: string }) =>
    request<RevisitTask>(`/revisit-tasks/${taskId}`, { method: 'PATCH', body: payload }),
  datasets: () => request<DatasetVersion[]>('/datasets/versions'),
  createDataset: (payload: { name: string; version: string; source_filter?: Record<string, unknown>; label_schema?: Record<string, unknown> }) =>
    request<DatasetVersion>('/datasets/versions', { method: 'POST', body: payload }),
  freezeDataset: (id: number, row_count: number) =>
    request<DatasetVersion>(`/datasets/versions/${id}/freeze`, { method: 'POST', body: { row_count } }),
  evaluations: () => request<ModelEvaluation[]>('/model-evaluations'),
  approveEvaluation: (id: number, approved_by: string) =>
    request<ModelEvaluation>(`/model-evaluations/${id}/approve`, { method: 'POST', body: { approved_by } }),
}

/* ---------- 登录与用户管理（决策 D15） ---------- */
export const authApi = {
  login: (username: string, password: string) =>
    request<LoginResult>('/auth/login', { method: 'POST', body: { username, password } }),
  me: () => request<User>('/auth/me'),
  changePassword: (old_password: string, new_password: string) =>
    request<void>('/auth/change-password', { method: 'POST', body: { old_password, new_password } }),
}

export interface UserCreatePayload {
  username: string
  display_name: string
  password: string
  role: UserRole
}
export interface UserUpdatePayload {
  display_name?: string
  role?: UserRole
  is_active?: boolean
  password?: string
}

export const usersApi = {
  list: () => request<User[]>('/users'),
  create: (payload: UserCreatePayload) => request<User>('/users', { method: 'POST', body: payload }),
  update: (id: number, payload: UserUpdatePayload) =>
    request<User>(`/users/${id}`, { method: 'PATCH', body: payload }),
}
