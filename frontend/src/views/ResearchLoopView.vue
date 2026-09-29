<script setup lang="ts">
/** 研究软件闭环：风险预测 → 主动任务 → 人工随访 → 模型评估记录。 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { patrolsApi, softwareLoopApi } from '../api'
import { errMsg } from '../api/http'
import type { DatasetVersion, ModelEvaluation, Patrol, RiskPrediction, RevisitTask } from '../types'

const patrols = ref<Patrol[]>([])
const selectedPatrol = ref<number | null>(null)
const predictions = ref<RiskPrediction[]>([])
const tasks = ref<RevisitTask[]>([])
const datasets = ref<DatasetVersion[]>([])
const evaluations = ref<ModelEvaluation[]>([])
const loading = ref(false)
const generating = ref(false)
const reviewer = ref(localStorage.getItem('agriscout_annotator') ?? '')

const selected = computed(() => patrols.value.find(p => p.id === selectedPatrol.value) ?? null)

/** 后端枚举值 → 界面文案（后端保持英文代码，展示层翻译）。 */
const LEVEL_TEXT: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', unknown: '证据不足' }
const LEVEL_TAG: Record<string, 'danger' | 'warning' | 'info' | 'success'> = { high: 'danger', medium: 'warning', unknown: 'info', low: 'success' }
const LEVEL_RANK: Record<string, number> = { high: 3, medium: 2, unknown: 1, low: 0 }
const TREND_TEXT: Record<string, string> = { rising: '↑ 上升', falling: '↓ 下降', stable: '→ 平稳', unknown: '无历史对比' }
const TASK_TYPE_TEXT: Record<string, string> = { revisit: '复巡', label: '专家标注', random: '随机抽查' }
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

function taskReasons(task: RevisitTask) {
  const reasons = task.rationale?.reasons
  return Array.isArray(reasons) ? reasons.map(r => text(REASON_TEXT, String(r))).join('、') : '系统排序'
}

/** field-5/grid2.5m/3_7 → 网格 3-7（2.5 m）；非网格键原样显示。 */
function regionLabel(key: string) {
  const m = /grid([\d.]+)m\/(-?\d+)_(-?\d+)$/.exec(key)
  return m ? `网格 ${m[2]}-${m[3]}（${m[1]} m）` : key
}

/**
 * 预测按采样点落库（复巡要落到具体点位），同一区域的点共享区域级结果；
 * 表格按「模型版本 + 区域」归并成一行，展开后逐点随访（随访仍是逐点记录，评估口径不变）。
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
const fmtTime = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

async function load() {
  loading.value = true
  try {
    patrols.value = (await patrolsApi.list({ analysis_status: 'done' })).items
    if (selectedPatrol.value == null && patrols.value.length) selectedPatrol.value = patrols.value[0].id
    await Promise.all([refreshLoop(), refreshGovernance()])
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}

async function refreshGovernance() {
  const [datasetRows, evaluationRows] = await Promise.all([
    softwareLoopApi.datasets(), softwareLoopApi.evaluations(),
  ])
  datasets.value = datasetRows
  evaluations.value = evaluationRows
}

async function refreshLoop() {
  if (!selectedPatrol.value) return
  predictions.value = await softwareLoopApi.predictions(selectedPatrol.value)
  tasks.value = await softwareLoopApi.tasks(selected.value?.field_id)
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
  } catch (e) { ElMessage.error(errMsg(e)) }
}

async function completeTask(row: RevisitTask) {
  try {
    if (row.status === 'queued') await softwareLoopApi.updateTask(row.id, { status: 'assigned' })
    if (row.status === 'queued' || row.status === 'assigned') await softwareLoopApi.updateTask(row.id, { status: 'running' })
    await softwareLoopApi.updateTask(row.id, { status: 'completed', result_note: '已完成人工确认' })
    await refreshLoop()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="head">
      <div>
        <h3>研究软件闭环 <span class="dim">风险预测 · 主动复巡 · 证据随访</span></h3>
        <p class="desc">这里展示可追溯的软件流程；启发式预测结果必须经过真实病种数据和独立测试验证。</p>
      </div>
      <div class="actions">
        <el-select v-model="selectedPatrol" placeholder="选择已分析巡检" style="width: 220px" @change="refreshLoop">
          <el-option v-for="p in patrols" :key="p.id" :label="`#${p.id} ${p.field_name ?? '未命名地块'}`" :value="p.id" />
        </el-select>
        <el-input v-model="reviewer" placeholder="复核人" style="width: 110px" />
        <el-button type="primary" :loading="generating" :disabled="!selectedPatrol" @click="generate">生成预测与任务</el-button>
      </div>
    </div>

    <el-alert v-if="!patrols.length && !loading" type="info" :closable="false" title="暂无已分析巡检，请先完成一次巡检上传和分析。" />

    <el-row :gutter="14">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>区域风险预测</span>
              <span v-if="regions.length" class="dim">
                {{ regions.length }} 个区域 · 高 {{ levelCounts.high }} · 中 {{ levelCounts.medium }}
                · 证据不足 {{ levelCounts.unknown }} · 低 {{ levelCounts.low }} · 覆盖 {{ predictions.length }} 个采样点
              </span>
            </div>
          </template>
          <el-table v-if="regions.length" :data="regions" row-key="key" size="small" stripe max-height="560">
            <el-table-column type="expand">
              <template #default="{ row }">
                <el-table :data="row.points" size="small" class="points" max-height="260">
                  <el-table-column label="采样点" width="110"><template #default="{ row: p }">ID {{ p.capture_point_id }}</template></el-table-column>
                  <el-table-column label="预测窗口" min-width="170"><template #default="{ row: p }">{{ fmtTime(p.forecast_start) }} ~ {{ fmtTime(p.forecast_end) }}</template></el-table-column>
                  <el-table-column label="随访" width="80"><template #default="{ row: p }"><span :class="p.status === 'closed' ? 'ok' : 'dim'">{{ p.status === 'closed' ? '已随访' : '待随访' }}</span></template></el-table-column>
                  <el-table-column label="操作" width="190">
                    <template #default="{ row: p }">
                      <el-button size="small" type="danger" plain :disabled="p.status === 'closed'" @click="confirmPrediction(p, 'confirmed_positive')">确认阳性</el-button>
                      <el-button size="small" type="success" plain :disabled="p.status === 'closed' || !windowEnded(p)" :title="windowEnded(p) ? '' : '预测窗口未结束，窗口内未发病不能确认阴性'" @click="confirmPrediction(p, 'confirmed_negative')">确认阴性</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column label="观察区域" min-width="140">
              <template #default="{ row }"><span :title="row.observation_key">{{ regionLabel(row.observation_key) }}</span></template>
            </el-table-column>
            <el-table-column label="风险" width="120">
              <template #default="{ row }"><el-tag :type="LEVEL_TAG[row.level] ?? 'info'">{{ text(LEVEL_TEXT, row.level) }} · {{ Math.round(row.probability * 100) }}%</el-tag></template>
            </el-table-column>
            <el-table-column label="趋势" width="100">
              <template #default="{ row }"><span :class="row.trend === 'unknown' ? 'dim' : ''" :title="row.trend === 'unknown' ? '回看窗口内该区域只有一次有效观测，无法判断趋势' : ''">{{ text(TREND_TEXT, row.trend) }}</span></template>
            </el-table-column>
            <el-table-column label="随访" width="90">
              <template #default="{ row }"><span :class="row.closed ? 'ok' : 'dim'">{{ row.closed }}/{{ row.points.length }} 点</span></template>
            </el-table-column>
            <el-table-column prop="model_version" label="模型" min-width="130" />
          </el-table>
          <el-empty v-else description="尚未生成预测" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never" header="复巡与主动学习任务" class="tasks-card">
          <el-timeline v-if="tasks.length">
            <el-timeline-item v-for="task in tasks" :key="task.id" :type="task.status === 'completed' ? 'success' : 'primary'">
              <div class="task-row"><b>{{ text(TASK_TYPE_TEXT, task.task_type) }} #{{ task.id }}</b><el-tag size="small" :type="TASK_STATUS_TAG[task.status] ?? 'primary'">{{ text(TASK_STATUS_TEXT, task.status) }}</el-tag></div>
              <div class="dim">优先级 {{ Math.round(task.priority * 100) }}% · {{ taskReasons(task) }}</div>
              <el-button v-if="task.status !== 'completed'" size="small" text type="primary" @click="completeTask(task)">标记完成</el-button>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无待执行任务" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="14" class="governance">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><div class="card-head"><span>数据集版本</span><el-button size="small" type="primary" plain @click="createDatasetDraft">创建草稿</el-button></div></template>
          <el-table :data="datasets" size="small">
            <el-table-column label="版本" min-width="150"><template #default="{ row }">{{ row.name }} / {{ row.version }}</template></el-table-column>
            <el-table-column prop="row_count" label="样本" width="70" />
            <el-table-column label="状态" width="80"><template #default="{ row }">{{ text(DATASET_STATUS_TEXT, row.status) }}</template></el-table-column>
            <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.status === 'draft'" size="small" text type="primary" @click="freezeDataset(row)">冻结</el-button></template></el-table-column>
          </el-table>
          <el-empty v-if="!datasets.length" description="暂无数据集版本" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" header="模型评估闸门">
          <el-table :data="evaluations" size="small">
            <el-table-column label="模型" min-width="140"><template #default="{ row }">{{ row.model_name }} / {{ row.model_version }}</template></el-table-column>
            <el-table-column label="数据划分" width="80"><template #default="{ row }">{{ text(SPLIT_TEXT, row.split) }}</template></el-table-column>
            <el-table-column label="状态" width="80"><template #default="{ row }">{{ text(EVAL_STATUS_TEXT, row.status) }}</template></el-table-column>
            <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.status === 'candidate'" size="small" text type="primary" @click="approveEvaluation(row)">批准</el-button></template></el-table-column>
          </el-table>
          <el-empty v-if="!evaluations.length" description="暂无评估记录" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; margin-bottom: 14px; }
.head h3 { margin: 0 0 5px; }
.desc, .dim { color: #8a978a; font-size: 12px; }
.actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.task-row { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.governance { margin-top: 14px; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.ok { color: #2f7d32; }
.points { margin: 0 12px 0 48px; width: auto; }
.tasks-card :deep(.el-card__body) { max-height: 600px; overflow-y: auto; }
</style>
