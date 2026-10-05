<script setup lang="ts">
/**
 * 研究软件闭环：风险预测 → 主动任务 → 人工随访 → 数据集与模型评估闸门（计划 0018 阶段 B 换外壳）。
 * 大棚按株关联，「观察对象」是株号，可点进单株时间线；大田是网格区域。只读账号看不到写操作。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis } from '@element-plus/icons-vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import { observationUnitsApi, patrolsApi, softwareLoopApi } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import type { DatasetVersion, ModelEvaluation, Patrol, RiskPrediction, RevisitTask } from '../types'
import { fieldClock } from '../utils/fieldTime'
import { taskReasons as planTaskReasons } from '../utils/planTask'

const auth = useAuthStore()
const ui = useUiStore()
const patrols = ref<Patrol[]>([])
const selectedPatrol = ref<number | null>(null)
const predictions = ref<RiskPrediction[]>([])
const tasks = ref<RevisitTask[]>([])
const datasets = ref<DatasetVersion[]>([])
const evaluations = ref<ModelEvaluation[]>([])
/** 株号 → 株 id（大棚地块），观察对象和任务里的株号据此链到单株时间线 */
const unitIds = ref(new Map<string, number>())
const loading = ref(false)
const generating = ref(false)
// 复核人默认取当前登录用户（D15）；服务端按登录用户署名记技术债
const reviewer = ref(auth.user?.display_name ?? readAnnotator())
function readAnnotator(): string {
  try { return localStorage.getItem('agriscout_annotator') ?? '' } catch { return '' }
}

const selected = computed(() => patrols.value.find((p) => p.id === selectedPatrol.value) ?? null)

/** 后端枚举值 → 界面文案（后端保持英文代码，展示层翻译）。 */
const LEVEL_TEXT: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', unknown: '证据不足' }
const LEVEL_TAG: Record<string, 'danger' | 'warning' | 'info' | 'success'> = { high: 'danger', medium: 'warning', unknown: 'info', low: 'success' }
const LEVEL_RANK: Record<string, number> = { high: 3, medium: 2, unknown: 1, low: 0 }
const TREND_TEXT: Record<string, string> = { rising: '↑ 上升', falling: '↓ 下降', stable: '→ 平稳', unknown: '无历史对比' }
const TASK_TYPE_TEXT: Record<string, string> = { revisit: '复巡', label: '专家标注', random: '随机抽查', coverage: '低频全覆盖' }
const TASK_STATUS_TEXT: Record<string, string> = { queued: '待派发', assigned: '已派发', running: '执行中', completed: '已完成', cancelled: '已取消' }
const TASK_STATUS_TAG: Record<string, 'success' | 'warning' | 'info' | 'primary'> = { completed: 'success', running: 'warning', cancelled: 'info' }
const REASON_TEXT: Record<string, string> = {
  quality_below_revisit_threshold: '证据质量不足，需补拍',
  risk_high: '风险高',
  change_high: '较上次变化大',
  highest_available_revisit_score: '复巡价值最高',
  uncertainty_high: '模型把握不大',
  quality_suitable_for_label: '照片质量适合标注',
  highest_available_label_score: '标注价值最高',
  representativeness_high: '代表性强',
  low_risk_coverage: '抽查低风险区域',
  highest_available_random_score: '抽查价值最高',
  cost_penalty_applied: '已计入路程成本',
}
const DATASET_STATUS_TEXT: Record<string, string> = { draft: '草稿', frozen: '已冻结' }
const EVAL_STATUS_TEXT: Record<string, string> = { candidate: '待审批', approved: '已批准', rejected: '已驳回' }
const SPLIT_TEXT: Record<string, string> = { train: '训练集', val: '验证集', test: '测试集' }
const text = (map: Record<string, string>, value: string) => map[value] ?? value

/** 研究闭环生成的任务写 reasons，巡检计划生成的写 triggers（0015），两种都认 */
function taskReasons(task: RevisitTask) {
  const reasons = task.rationale?.reasons
  if (Array.isArray(reasons)) return reasons.map((r) => text(REASON_TEXT, String(r))).join('、')
  const triggers = planTaskReasons(task)
  return triggers.length ? triggers.join('、') : '系统排序'
}

/** field-5/grid2.5m/3_7 → 网格 3-7（2.5 m）；株号等非网格键原样显示。 */
/** 株的区域键是 field-{id}/unit/{株号}（计划 0014），大田是网格键 */
const UNIT_KEY = /\/unit\/([^/]+)$/
function regionLabel(key: string) {
  const unit = UNIT_KEY.exec(key)
  if (unit) return unit[1]
  const m = /grid([\d.]+)m\/(-?\d+)_(-?\d+)$/.exec(key)
  return m ? `网格 ${m[2]}-${m[3]}（${m[1]} m）` : key
}
function unitIdOf(key: string): number | undefined {
  const unit = UNIT_KEY.exec(key)
  return unit ? unitIds.value.get(unit[1]) : undefined
}

/**
 * 预测按采样点落库（复巡要落到具体点位），同一观察对象（株或网格）的点共享结果；
 * 表格按「模型版本 + 观察对象」归并成一行，展开后逐点随访（随访仍是逐点记录，评估口径不变）。
 */
interface RegionRow {
  key: string
  observation_key: string
  model_version: string
  level: string
  probability: number
  trend: string
  points: RiskPrediction[]
  closed: number
}
const regions = computed<RegionRow[]>(() => {
  const byKey = new Map<string, RegionRow>()
  for (const p of predictions.value) {
    const key = `${p.model_version}|${p.observation_key}`
    let row = byKey.get(key)
    if (!row) {
      row = { key, observation_key: p.observation_key, model_version: p.model_version, level: p.level,
              probability: p.probability, trend: p.trend, points: [], closed: 0 }
      byKey.set(key, row)
    }
    row.points.push(p)
    if (p.status === 'closed') row.closed++
  }
  return [...byKey.values()].sort((a, b) =>
    (LEVEL_RANK[b.level] ?? 0) - (LEVEL_RANK[a.level] ?? 0) || b.probability - a.probability)
})
const levelCounts = computed(() => {
  const counts: Record<string, number> = { high: 0, medium: 0, unknown: 0, low: 0 }
  for (const r of regions.value) counts[r.level] = (counts[r.level] ?? 0) + 1
  return counts
})

async function load() {
  loading.value = true
  try {
    patrols.value = (await patrolsApi.list({ analysis_status: 'done' })).items
    if (selectedPatrol.value == null && patrols.value.length) selectedPatrol.value = patrols.value[0].id
    await Promise.all([refreshLoop(), refreshGovernance()])
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}

async function refreshGovernance() {
  const [datasetRows, evaluationRows] = await Promise.all([softwareLoopApi.datasets(), softwareLoopApi.evaluations()])
  datasets.value = datasetRows
  evaluations.value = evaluationRows
}

async function refreshLoop() {
  if (!selectedPatrol.value) return
  const fieldId = selected.value?.field_id
  const [rows, taskRows] = await Promise.all([softwareLoopApi.predictions(selectedPatrol.value), softwareLoopApi.tasks(fieldId)])
  predictions.value = rows
  tasks.value = taskRows
  if (fieldId != null) {
    ui.setCurrentField(fieldId)
    try {
      unitIds.value = new Map((await observationUnitsApi.list(fieldId)).map((u) => [u.key, u.id]))
    } catch { unitIds.value = new Map() /* 没有株档案只是不出链接 */ }
  }
}
async function onPatrolChange() {
  try { await refreshLoop() } catch (e) { ElMessage.error(errMsg(e)) }
}

async function generate() {
  if (!selectedPatrol.value || !selected.value) return
  generating.value = true
  try {
    predictions.value = await softwareLoopApi.generatePredictions(selectedPatrol.value)
    const generated = await softwareLoopApi.generateTasks(selected.value.field_id, selectedPatrol.value)
    ElMessage.success(`已生成 ${generated.length} 个复巡/标注任务`)
    await refreshLoop()
    await refreshGovernance()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { generating.value = false }
}

async function createDatasetDraft() {
  try {
    if (!selectedPatrol.value) {
      ElMessage.warning('请先选择巡检，再创建数据集草稿')
      return
    }
    const name = (await ElMessageBox.prompt('数据集名称', '创建数据集草稿', { inputValue: 'wheat-review' })).value.trim()
    const version = (await ElMessageBox.prompt('版本号', '创建数据集草稿', { inputValue: 'v1' })).value.trim()
    if (!name || !version) return
    await softwareLoopApi.createDataset({ name, version, source_filter: { patrol_id: selectedPatrol.value }, label_schema: { target: 'disease' } })
    ElMessage.success('数据集草稿已创建')
    await refreshGovernance()
  } catch (e) { if (e !== 'cancel') ElMessage.error(errMsg(e)) }
}

async function freezeDataset(row: DatasetVersion) {
  try {
    const result = await ElMessageBox.prompt('冻结前确认样本行数', '冻结数据集', { inputValue: String(row.row_count) })
    const count = Number(result.value)
    if (!Number.isInteger(count) || count < 0) throw new Error('行数必须是非负整数')
    await softwareLoopApi.freezeDataset(row.id, count)
    ElMessage.success('数据集已冻结')
    await refreshGovernance()
  } catch (e) { if (e !== 'cancel') ElMessage.error(errMsg(e)) }
}

async function approveEvaluation(row: ModelEvaluation) {
  try {
    await ElMessageBox.confirm(`确认批准 ${row.model_name} ${row.model_version}？`, '模型发布闸门')
    await softwareLoopApi.approveEvaluation(row.id, reviewer.value.trim() || '未署名')
    ElMessage.success('模型评估已批准')
    await refreshGovernance()
  } catch (e) { if (e !== 'cancel') ElMessage.error(errMsg(e)) }
}

/** 阴性标签要求整个预测窗口已走完（后端同样校验，申报书 8.2）。 */
function windowEnded(row: RiskPrediction): boolean {
  return new Date(row.forecast_end).getTime() <= Date.now()
}

async function confirmPrediction(row: RiskPrediction, status: 'confirmed_positive' | 'confirmed_negative') {
  try {
    if (row.status === 'closed') return
    const evidence = (await ElMessageBox.prompt('请输入复查照片、标注或其他证据引用', '提交随访证据', { inputPlaceholder: '例如：/media/recheck-001.jpg' })).value.trim()
    if (!evidence) return
    await softwareLoopApi.followUp(row.id, {
      status, reviewed_by: reviewer.value.trim() || '未署名', event_confirmed: status === 'confirmed_positive',
      evidence: { reference: evidence, prediction_id: row.id, capture_point_id: row.capture_point_id },
      note: status === 'confirmed_positive' ? '人工复核确认阳性' : '人工复核确认阴性',
    })
    ElMessage.success('随访结论已保存')
    await refreshLoop()
  } catch (e) { if (e !== 'cancel') ElMessage.error(errMsg(e)) }
}

async function completeTask(row: RevisitTask) {
  try {
    await softwareLoopApi.completeTask(row, '已完成人工确认')
    await refreshLoop()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(load)
</script>

<template>
  <PageHeader title="研究闭环" subtitle="风险预测 · 主动复巡 · 证据随访；启发式预测结果必须经过真实病种数据和独立测试验证">
    <template #actions>
      <el-select v-model="selectedPatrol" placeholder="选择已分析巡检" class="patrol-select" @change="onPatrolChange">
        <el-option v-for="p in patrols" :key="p.id" :label="`#${p.id} ${p.field_name ?? '未命名地块'}`" :value="p.id" />
      </el-select>
      <template v-if="!auth.isViewer">
        <el-input v-model="reviewer" placeholder="复核人" class="reviewer" />
        <el-button type="primary" :loading="generating" :disabled="!selectedPatrol" @click="generate">生成预测与任务</el-button>
      </template>
    </template>
  </PageHeader>

  <EmptyState v-if="!patrols.length && !loading" :icon="DataAnalysis" title="还没有分析完成的巡检" description="先完成一次巡检上传和分析。" />

  <div v-loading="loading" class="grid">
    <SectionCard title="风险预测" class="predictions" flush
                 :subtitle="regions.length ? `${regions.length} 个观察对象 · 高 ${levelCounts.high} · 中 ${levelCounts.medium} · 证据不足 ${levelCounts.unknown} · 低 ${levelCounts.low} · 覆盖 ${predictions.length} 个采样点` : '大棚按株、大田按网格区域'">
      <el-table v-if="regions.length" :data="regions" row-key="key" max-height="560">
        <el-table-column type="expand">
          <template #default="{ row }">
            <el-table :data="row.points" size="small" class="points" max-height="260">
              <el-table-column label="采样点" width="110"><template #default="{ row: p }">ID {{ p.capture_point_id }}</template></el-table-column>
              <el-table-column label="预测窗口" min-width="200">
                <template #default="{ row: p }"><span class="tabular">{{ fieldClock(p.forecast_start) }} ~ {{ fieldClock(p.forecast_end) }}</span></template>
              </el-table-column>
              <el-table-column label="随访" width="80">
                <template #default="{ row: p }"><span :class="p.status === 'closed' ? 'ok' : 'muted'">{{ p.status === 'closed' ? '已随访' : '待随访' }}</span></template>
              </el-table-column>
              <el-table-column v-if="!auth.isViewer" label="操作" width="190">
                <template #default="{ row: p }">
                  <el-button size="small" type="danger" plain :disabled="p.status === 'closed'" @click="confirmPrediction(p, 'confirmed_positive')">确认阳性</el-button>
                  <el-button size="small" type="success" plain :disabled="p.status === 'closed' || !windowEnded(p)"
                             :title="windowEnded(p) ? '' : '预测窗口未结束，窗口内未发病不能确认阴性'" @click="confirmPrediction(p, 'confirmed_negative')">确认阴性</el-button>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </el-table-column>
        <el-table-column label="观察对象" min-width="140">
          <template #default="{ row }">
            <router-link v-if="unitIdOf(row.observation_key) != null" :to="`/units/${unitIdOf(row.observation_key)}`" class="mono"
                         :title="row.observation_key">{{ regionLabel(row.observation_key) }}</router-link>
            <span v-else :title="row.observation_key">{{ regionLabel(row.observation_key) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="风险" width="130">
          <template #default="{ row }">
            <el-tag :type="LEVEL_TAG[row.level] ?? 'info'" effect="plain">{{ text(LEVEL_TEXT, row.level) }} · {{ Math.round(row.probability * 100) }}%</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="趋势" width="100">
          <template #default="{ row }">
            <span :class="{ muted: row.trend === 'unknown' }" :title="row.trend === 'unknown' ? '回看窗口内只有一次有效观测，无法判断趋势' : ''">{{ text(TREND_TEXT, row.trend) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="随访" width="90">
          <template #default="{ row }"><span :class="row.closed ? 'ok' : 'muted'">{{ row.closed }}/{{ row.points.length }} 点</span></template>
        </el-table-column>
        <el-table-column prop="model_version" label="模型" min-width="130" />
      </el-table>
      <EmptyState v-else compact title="尚未生成预测" :description="auth.isViewer ? '' : '选好巡检后点「生成预测与任务」'" />
    </SectionCard>

    <SectionCard title="复巡与主动学习任务" :subtitle="selected ? `${selected.field_name ?? `地块 #${selected.field_id}`} 的全部任务` : ''" class="tasks">
      <el-timeline v-if="tasks.length">
        <el-timeline-item v-for="task in tasks" :key="task.id" :type="task.status === 'completed' ? 'success' : 'primary'">
          <div class="task-row">
            <b>{{ text(TASK_TYPE_TEXT, task.task_type) }} #{{ task.id }}</b>
            <router-link v-if="task.observation_unit_id" :to="`/units/${task.observation_unit_id}`" class="mono text-13">
              {{ (task.parameters.observation_key as string | undefined) ?? `株 #${task.observation_unit_id}` }}
            </router-link>
            <el-tag size="small" effect="plain" :type="TASK_STATUS_TAG[task.status] ?? 'primary'">{{ text(TASK_STATUS_TEXT, task.status) }}</el-tag>
          </div>
          <div class="muted text-12">优先级 {{ Math.round(task.priority * 100) }}% · {{ taskReasons(task) }}</div>
          <el-button v-if="!auth.isViewer && task.status !== 'completed' && task.status !== 'cancelled'" size="small" text type="primary"
                     @click="completeTask(task)">标记完成</el-button>
        </el-timeline-item>
      </el-timeline>
      <EmptyState v-else compact title="暂无待执行任务" />
    </SectionCard>

    <SectionCard title="数据集版本" subtitle="冻结后才能绑定模型评估" flush>
      <template v-if="!auth.isViewer" #actions>
        <el-button size="small" type="primary" plain @click="createDatasetDraft">创建草稿</el-button>
      </template>
      <el-table :data="datasets">
        <el-table-column label="版本" min-width="150"><template #default="{ row }">{{ row.name }} / {{ row.version }}</template></el-table-column>
        <el-table-column prop="row_count" label="样本" width="80" align="right" />
        <el-table-column label="状态" width="90"><template #default="{ row }">{{ text(DATASET_STATUS_TEXT, row.status) }}</template></el-table-column>
        <el-table-column v-if="!auth.isViewer" label="操作" width="90">
          <template #default="{ row }"><el-button v-if="row.status === 'draft'" size="small" text type="primary" @click="freezeDataset(row)">冻结</el-button></template>
        </el-table-column>
        <template #empty><span class="muted text-13">暂无数据集版本</span></template>
      </el-table>
    </SectionCard>

    <SectionCard title="模型评估闸门" subtitle="只能绑定已冻结数据集的测试集才能批准发布" flush>
      <el-table :data="evaluations">
        <el-table-column label="模型" min-width="140"><template #default="{ row }">{{ row.model_name }} / {{ row.model_version }}</template></el-table-column>
        <el-table-column label="数据划分" width="90"><template #default="{ row }">{{ text(SPLIT_TEXT, row.split) }}</template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }">{{ text(EVAL_STATUS_TEXT, row.status) }}</template></el-table-column>
        <el-table-column v-if="!auth.isViewer" label="操作" width="90">
          <template #default="{ row }"><el-button v-if="row.status === 'candidate'" size="small" text type="primary" @click="approveEvaluation(row)">批准</el-button></template>
        </el-table-column>
        <template #empty><span class="muted text-13">暂无评估记录</span></template>
      </el-table>
    </SectionCard>
  </div>
</template>

<style scoped>
.patrol-select { width: 220px; }
.reviewer { width: 120px; }
.grid { display: grid; grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); gap: var(--space-4); align-items: start; }
.tasks :deep(.sc-body) { max-height: 620px; overflow-y: auto; }
.task-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.task-row .el-tag { margin-left: auto; }
.mono { font-family: var(--font-mono); }
.ok { color: var(--success-ink); }
.points { margin: 0 var(--space-3) 0 48px; width: auto; }
@media (max-width: 1023px) {
  .grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
