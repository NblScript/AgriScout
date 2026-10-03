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
  facility_type: FacilityType | null
  created_at: string
  updated_at: string
}

/** 设施类型（计划 0014）；空视为大田 */
export type FacilityType = 'open_field' | 'solar_greenhouse' | 'plastic_tunnel'

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

/* ================= M6 可视化：巡检/采样点/建议 ================= */

export interface Page<T> {
  items: T[]
  total: number
  skip: number
  limit: number
}

export interface WeatherSample {
  temp_c: number | null
  humidity_pct: number | null
  light_lux: number | null
  wind_mps: number | null
  rain_mm: number | null
  soil_temp_c: number | null
  soil_moisture_pct: number | null
}

export interface DiseaseDetection {
  type?: string
  label?: string
  confidence?: number
  /** 病害模型（stripe_rust）：阳性图块框，归一化 [x, y, w, h] */
  boxes?: number[][]
  /** 病害模型：阳性图块占全部图块的比例 */
  area_ratio?: number
  model?: string
  [k: string]: unknown
}

export interface PointAnalysis {
  id: number
  capture_point_id: number
  analyzer_version: string
  growth_stage: { name?: string; [k: string]: unknown } | null
  vigor_level: number | null
  ndvi: number | null
  disease_detections: DiseaseDetection[] | null
  risk_score: number | null
  detail: Record<string, unknown> | null
  analyzed_at: string
}

export interface CapturePointFull {
  id: number
  patrol_id: number
  seq: number
  distance_m: number
  lng: number
  lat: number
  captured_at: string
  photo_url: string | null
  weather: WeatherSample | null
  analysis: PointAnalysis | null
  // 协议 v2 最小子集（计划 0014）；v1 包为空
  observation_key: string | null
  observation_unit_id: number | null
  route_chainage_m: number | null
  distance_source: string | null
  position_source: string | null
  view: ViewMeta | null
}

/** 视角元数据（协议字段 view，计划 0013「共同约定」） */
export interface ViewMeta {
  side: 'upper' | 'under' | 'unknown'
  pitch_deg: number | null
  yaw_deg: number | null
  height_m: number | null
  fill_light: boolean | null
  attempt: number
  accepted: boolean | null
  quality: ImageQuality | null
}

/** 图像质量 iq-rule-v1（车端 view.quality 与平台 analysis.detail.image_quality 同结构） */
export interface ImageQuality {
  method: string
  ok: boolean
  reasons: string[]
  sharpness?: number | null
  mean_luma?: number | null
  clip_high?: number | null
  clip_low?: number | null
  backlit?: boolean | null
}

/* ---------- 株档案与单株时间线（计划 0014） ---------- */

export type UnitStatus = 'active' | 'retired'
export type UnitSource = 'manual' | 'bulk' | 'ingest'

export interface ObservationUnit {
  id: number
  field_id: number
  key: string
  row_no: number | null
  position_no: number | null
  chainage_m: number | null
  tag_code: string | null
  status: UnitStatus
  created_from: UnitSource
  note: string | null
  created_at: string
  updated_at: string
}

export interface TimelinePhoto {
  capture_point_id: number
  patrol_id: number
  captured_at: string
  photo_url: string | null
  view: ViewMeta | null
  analysis: {
    risk_score: number | null
    disease_detections: Record<string, unknown>[] | null
    analyzer_version: string
    image_quality: ImageQuality | null
  } | null
}

export interface TimelineAnnotation {
  id: number
  capture_point_id: number
  label: string
  annotator_name: string
  note: string | null
  updated_at: string
}

export interface TimelinePrediction {
  id: number
  capture_point_id: number | null
  target_event: string
  model_version: string
  probability: number
  level: string
  trend: string
  status: string
  follow_up_status: string | null
}

export interface TimelineDay {
  field_date: string
  photos: TimelinePhoto[]
  annotations: TimelineAnnotation[]
  predictions: TimelinePrediction[]
}

export interface UnitTimeline {
  unit: ObservationUnit
  days: TimelineDay[]
}

export interface Patrol {
  id: number
  field_id: number
  field_name: string | null
  planting_id: number | null
  device_id: number | null
  device_code: string | null
  started_at: string
  ended_at: string | null
  status: string
  analysis_status: 'pending' | 'running' | 'done' | 'error'
}

export interface PatrolDetail extends Patrol {
  track: { type: string; coordinates: number[][] } | null
  point_count: number
  notes: string | null
  schema_version: string
  client_package_id: string | null
}

export interface RuleSnapshot {
  rule_key: string
  tier: string
  priority: string
  condition: Record<string, unknown>
  action: string
  params: Record<string, unknown> | null
  source: string | null
  version: number
}

export type AdviceStatus = 'suggested' | 'accepted' | 'rejected'

export interface Advice {
  id: number
  patrol_id: number
  capture_point_id: number | null
  rule_id: number | null
  rule_key: string
  rule_snapshot: RuleSnapshot
  content: string
  priority: string
  status: AdviceStatus
  created_at: string
}

export interface AnalysisSummary {
  patrol_id: number
  analysis_status: string
  total_points: number
  analyzed_points: number
  analyzer_version: string | null
  vigor_distribution: Record<string, number>
  avg_ndvi: number | null
  avg_risk_score: number | null
  stage_histogram: Record<string, number>
  stress_flagged_points: number
}

/* ================= M6+ 标注回流：人工复核 ================= */
export type AnnotationLabel = 'normal' | 'dry_stress' | 'suspected_disease' | 'other'

export interface Annotation {
  id: number
  patrol_id: number
  capture_point_id: number
  label: AnnotationLabel
  annotator_name: string
  bbox: number[] | null
  note: string | null
  created_at: string
  updated_at: string
}

export interface AnnotationSummary {
  patrol_id: number
  points_total: number
  annotated_points: number
  annotations_total: number
}

export const ANNOTATION_LABELS: Record<AnnotationLabel, string> = {
  normal: '正常',
  dry_stress: '干旱胁迫',
  suspected_disease: '疑似病害',
  other: '其他',
}

export const ANNOTATION_TAG_TYPES: Record<AnnotationLabel, string> = {
  normal: 'success',
  dry_stress: 'warning',
  suspected_disease: 'danger',
  other: 'info',
}

/** 长势等级 → 展示色（1 差 → 5 旺） */
export const VIGOR_COLORS: Record<number, string> = {
  1: '#d32f2f',
  2: '#ef6c00',
  3: '#f9a825',
  4: '#7cb342',
  5: '#2e7d32',
}
export const NO_ANALYSIS_COLOR = '#9e9e9e'

export const ADVICE_STATUS_LABELS: Record<AdviceStatus, string> = {
  suggested: '待处理',
  accepted: '已采纳',
  rejected: '已驳回',
}

/* ================= 规则线 L1：规则修订审批 ================= */

export interface RuleRevision {
  id: number
  rule_key: string
  action: 'modify' | 'add' | 'deactivate' | string
  draft: Record<string, unknown>
  reason: string
  shadow_result: {
    patrols_checked: number[]
    added_total: number
    removed_total: number
    added_sample: string[]
    removed_sample: string[]
    per_patrol: { patrol_id: number; before: number; after: number; added: number; removed: number }[]
  } | null
  status: 'draft' | 'approved' | 'rejected' | string
  decided_by: string | null
  decide_note: string | null
  model: string
  prompt_version: string
  applied_version: number | null
  created_at: string
}

/* ================= 建议线 L2：诊断 Agent ================= */

export interface AgentChatResult {
  id: number
  patrol_id: number | null
  question: string
  answer: string
  tool_calls_trace: { tool: string; arguments: Record<string, unknown> }[]
  model: string
  prompt_version: string
  created_at: string
}

/* ================= 建议线 L1：巡检 AI 农事报告 ================= */

export interface PatrolReport {
  id: number
  patrol_id: number
  content: string
  model: string
  prompt_version: string
  input_digest: Record<string, unknown>
  created_at: string
  updated_at: string
}

/* ================= 指挥大屏：平台聚合统计 ================= */

export interface RecentPatrolStat {
  patrol_id: number
  field_name: string | null
  started_at: string
  point_count: number
  analyzed_points: number
  avg_ndvi: number | null
  avg_risk_score: number | null
  /** 键为长势等级 "1"-"5" */
  vigor_distribution: Record<string, number>
  stress_points: number
}

export interface StatsOverview {
  fields: number
  crops: number
  plantings: number
  devices: number
  patrols: number
  capture_points: number
  analyzed_points: number
  annotations: number
  advices_total: number
  advices_suggested: number
  advices_accepted: number
  advices_rejected: number
  recent_patrols: RecentPatrolStat[]
}

/* ================= 研究软件闭环：风险/复巡/评估 ================= */
export interface RiskPrediction {
  id: number
  patrol_id: number
  capture_point_id: number | null
  observation_key: string
  target_event: string
  forecast_hours: number
  forecast_start: string
  forecast_end: string
  probability: number
  level: 'low' | 'medium' | 'high' | 'unknown'
  trend: string
  confidence: number
  model_version: string
  evidence: Record<string, unknown>
  status: string
  created_at: string
  updated_at: string
}

export interface RevisitTask {
  id: number
  field_id: number
  patrol_id: number | null
  capture_point_id: number | null
  device_id: number | null
  risk_prediction_id: number | null
  task_type: 'revisit' | 'label' | 'random'
  status: string
  priority: number
  value_score: number
  rationale: Record<string, unknown>
  parameters: Record<string, unknown>
  created_by: string
  scheduled_at: string | null
  completed_at: string | null
  result_note: string | null
  created_at: string
  updated_at: string
}

export interface DatasetVersion {
  id: number
  name: string
  version: string
  status: string
  row_count: number
  source_filter: Record<string, unknown>
  label_schema: Record<string, unknown>
  created_by: string
  frozen_at: string | null
  snapshot_sha256: string | null
  snapshot_summary: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ModelEvaluation {
  id: number
  dataset_version_id: number | null
  model_name: string
  model_version: string
  split: string
  metrics: Record<string, unknown>
  status: string
  notes: string | null
  evaluated_at: string
  approved_by: string | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

export interface DeviceHeartbeat {
  id: number
  device_id: number
  client_heartbeat_id: string | null
  observed_at: string
  status: string
  execution_phase: string
  mission_id: number | null
  position_source: string
  queue_size: number
  battery_pct: number | null
  temperature_c: number | null
  error_code: string | null
  payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

/* ---------- 登录与用户（决策 D15） ---------- */
export type UserRole = 'admin' | 'operator' | 'viewer'
export const ROLE_LABELS: Record<UserRole, string> = { admin: '管理员', operator: '操作员', viewer: '只读' }

export interface User {
  id: number
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

export interface LoginResult {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  user: User
}

export interface DeviceEvent {
  id: number
  device_id: number | null
  mission_id: number | null
  client_event_id: string | null
  event_type: string
  severity: string
  source: string
  occurred_at: string
  is_fault_injected: boolean
  fault_type: string | null
  fault_active: boolean | null
  payload: Record<string, unknown>
  note: string | null
  created_at: string
  updated_at: string
}
