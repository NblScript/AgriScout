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

export const FACILITY_LABELS: Record<FacilityType, string> = {
  open_field: '大田',
  solar_greenhouse: '日光温室',
  plastic_tunnel: '塑料大棚',
}

/** 大棚类地块（日光温室、塑料大棚）走按株巡检的页面；其余按大田处理 */
export function isGreenhouse(field: Pick<Field, 'facility_type'> | null | undefined): boolean {
  return field?.facility_type === 'solar_greenhouse' || field?.facility_type === 'plastic_tunnel'
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

/**
 * 检出类型（analysis.disease_detections[].type）→ 中文名（计划 0018）：病斑框、地图提示、图例都按这里显示，页面里不写死病名。
 * 接入新的病害模型时在这里加它的类型；没登记的类型退回检出自带的 label 或类型码。
 */
export const DETECTION_TYPE_LABELS: Record<string, string> = {
  stripe_rust: '条锈病',
  suspected_stress: '疑似胁迫',
}

/** 病害模型给出的检出（带病斑框、地图上标红圈）；颜色规则的「疑似胁迫」不算 */
export const DISEASE_MODEL_TYPES: ReadonlySet<string> = new Set(['stripe_rust'])

export function detectionLabel(d: { type?: string; label?: string }): string {
  return (d.type && DETECTION_TYPE_LABELS[d.type]) || d.label || d.type || '检出'
}

export function isDiseaseModelDetection(d: { type?: string }): boolean {
  return !!d.type && DISEASE_MODEL_TYPES.has(d.type)
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

/** iq-rule-v1 的不合格原因 */
export const QUALITY_REASON_LABELS: Record<string, string> = {
  blurry: '模糊',
  overexposed: '过曝',
  underexposed: '欠曝',
  backlit: '逆光',
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

/** 风险预测等级（时间线、研究闭环共用） */
export const RISK_LEVEL_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低', unknown: '不明' }
export const RISK_LEVEL_TAG_TYPES: Record<string, 'danger' | 'warning' | 'info'> = { high: 'danger', medium: 'warning', low: 'info' }

/** 预测的随访结论 */
export const FOLLOW_UP_LABELS: Record<string, string> = {
  pending: '待随访',
  confirmed_positive: '确认阳性',
  confirmed_negative: '确认阴性',
  insufficient: '证据不足',
  intervened: '已处置',
  unknown: '未知',
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

export const ANALYSIS_STATUS_LABELS: Record<Patrol['analysis_status'], string> = {
  pending: '待分析',
  running: '分析中',
  done: '已完成',
  error: '失败',
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
export type AnnotationLabel =
  | 'normal'
  | 'dry_stress'
  | 'suspected_disease'
  | 'other'
  | 'downy_mildew_early'
  | 'downy_mildew_symptomatic'

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
  downy_mildew_early: '霜霉病早期',
  downy_mildew_symptomatic: '霜霉病明显',
}

export const ANNOTATION_TAG_TYPES: Record<AnnotationLabel, string> = {
  normal: 'success',
  dry_stress: 'warning',
  suspected_disease: 'danger',
  other: 'info',
  downy_mildew_early: 'warning',
  downy_mildew_symptomatic: 'danger',
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
  observation_unit_id: number | null
  task_type: 'revisit' | 'label' | 'random' | 'coverage'
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

export const TASK_STATUS_LABELS: Record<string, string> = {
  queued: '待领取',
  assigned: '已分配',
  running: '执行中',
  completed: '已完成',
  cancelled: '已取消',
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

/* ================= 计划 0015：棚内环境、每株状态、巡检计划 ================= */
export interface EnvHour {
  hour: string
  count: number
  missing: boolean
  temp_c: number | null
  humidity_pct: number | null
  dewpoint_depression_min: number | null
  leaf_wetness_max: number | null
  favorable: boolean
  wet: boolean
}

export interface EnvDay {
  field_date: string
  favorable_hours: number
  wet_hours: number
  night_wet_hours: number
  night_coverage: number
  diurnal_range: number | null
  coverage: number
}

export interface EnvIndex {
  method: string
  /** null = 覆盖率不足，按无环境信息处理（不是低风险） */
  env_index: number | null
  as_of: string
  window_hours: number
  favorable_hours: number
  wet_hours: number
  coverage: number
  reason: string | null
}

export interface MorningWindow {
  date: string
  start: string
  end: string
  night_of: string
  night_wet_hours: number
  reason: string
}

export interface EnvSummary {
  field_id: number
  since: string
  until: string
  sensors: string[]
  hourly: EnvHour[]
  daily: EnvDay[]
  index: EnvIndex
  morning_window: MorningWindow | null
  params: Record<string, unknown>
}

export type PlantStateValue = 'healthy' | 'early' | 'symptomatic' | 'unknown'
export const PLANT_STATE_LABELS: Record<PlantStateValue, string> = {
  healthy: '健康',
  early: '早期',
  symptomatic: '明显',
  unknown: '不明',
}

/** 每株状态的来源（D18：人工结论优先，只有模型结果时为占位分数） */
export const PLANT_SOURCE_LABELS: Record<'human' | 'model' | 'none', string> = {
  human: '人工确认',
  model: '模型（占位）',
  none: '还没有结论',
}

/** 人工确认株状态的四个选项（时间线「确认状态」与待确认页共用；写成标注） */
export const CONFIRM_OPTIONS: { label: AnnotationLabel; text: string; state: PlantStateValue | null }[] = [
  { label: 'normal', text: '健康', state: 'healthy' },
  { label: 'downy_mildew_early', text: '早期', state: 'early' },
  { label: 'downy_mildew_symptomatic', text: '明显', state: 'symptomatic' },
  { label: 'other', text: '其他', state: null },
]

export interface PlantState {
  unit_id: number
  key: string
  row_no: number | null
  position_no: number | null
  state: PlantStateValue
  source: 'human' | 'model' | 'none'
  confidence: number
  model_score: number | null
  last_seen_at: string | null
  last_under_ok_at: string | null
  last_under_accepted: boolean | null
  reviewed_at: string | null
  analyzer_version: string | null
}

export type PlanListName = 'confirm' | 'reshoot' | 'coverage' | 'random'
export const PLAN_LIST_LABELS: Record<PlanListName, string> = {
  confirm: '推给人确认',
  reshoot: '叶背补拍',
  coverage: '低频全覆盖',
  random: '随机抽查',
}

/** 名单的短名（标签、图例用） */
export const PLAN_LIST_SHORT_LABELS: Record<PlanListName, string> = {
  confirm: '确认',
  reshoot: '补拍',
  coverage: '全覆盖',
  random: '抽查',
}

/** 任务类型 → 名单（计划 0015：确认→label、补拍→revisit、全覆盖→coverage、抽查→random） */
export const TASK_TYPE_LIST: Record<RevisitTask['task_type'], PlanListName> = {
  label: 'confirm',
  revisit: 'reshoot',
  coverage: 'coverage',
  random: 'random',
}

/** 计划理由里的触发原因 */
export const PLAN_TRIGGER_LABELS: Record<string, string> = {
  model_early: '模型判早期',
  model_score_over_confirm_threshold: '模型分超确认阈值',
  top_reshoot_score: '补拍分靠前',
  last_under_rejected: '上次叶背不合格',
  morning_window: '清晨窗口',
  coverage_due: '超过全覆盖周期',
  never_seen: '从未拍到',
  random_spot_check: '随机抽查',
}

export interface PlanItem {
  unit_id: number
  key: string
  row_no: number | null
  position_no: number | null
  list_name: PlanListName
  task_id: number
  task_type: string
  task_status: string
  score: number
  priority: number
  rationale: Record<string, unknown>
}

export interface PatrolPlan {
  field_id: number
  plan_version: string
  plan_date: string
  /** 本地块第几次生成计划；重新生成时上一版里还在排队、没入选的任务作废 */
  generation: number | null
  generated_at: string | null
  seed: string
  units: number
  reshoot_budget: number
  env: Record<string, unknown> & { env_index: number | null; env_missing?: boolean; coverage?: number }
  window: MorningWindow | null
  confirm: PlanItem[]
  reshoot: PlanItem[]
  coverage: PlanItem[]
  random: PlanItem[]
  params: Record<string, unknown> | null
}
