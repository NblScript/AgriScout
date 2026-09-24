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
function taskReasons(task: RevisitTask) {
  const reasons = task.rationale?.reasons
  return Array.isArray(reasons) ? reasons.join('、') : '系统排序'
}

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
        <el-card shadow="never" header="区域风险预测">
          <el-table :data="predictions" size="small" stripe>
            <el-table-column prop="observation_key" label="观察区域" min-width="160" />
            <el-table-column label="风险" width="100">
              <template #default="{ row }"><el-tag :type="row.level === 'high' ? 'danger' : row.level === 'medium' ? 'warning' : 'success'">{{ row.level }} · {{ Math.round(row.probability * 100) }}%</el-tag></template>
            </el-table-column>
            <el-table-column prop="trend" label="趋势" width="80" />
            <el-table-column prop="model_version" label="模型" min-width="150" />
            <el-table-column label="随访" width="190">
              <template #default="{ row }">
                <el-button size="small" type="danger" plain :disabled="row.status === 'closed'" @click="confirmPrediction(row, 'confirmed_positive')">确认阳性</el-button>
                <el-button size="small" type="success" plain :disabled="row.status === 'closed'" @click="confirmPrediction(row, 'confirmed_negative')">确认阴性</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!predictions.length" description="尚未生成预测" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never" header="复巡与主动学习任务">
          <el-timeline v-if="tasks.length">
            <el-timeline-item v-for="task in tasks" :key="task.id" :type="task.status === 'completed' ? 'success' : 'primary'">
              <div class="task-row"><b>{{ task.task_type === 'revisit' ? '复巡' : task.task_type === 'label' ? '专家标注' : '随机抽查' }} #{{ task.id }}</b><el-tag size="small">{{ task.status }}</el-tag></div>
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
            <el-table-column prop="status" label="状态" width="80" />
            <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.status === 'draft'" size="small" text type="primary" @click="freezeDataset(row)">冻结</el-button></template></el-table-column>
          </el-table>
          <el-empty v-if="!datasets.length" description="暂无数据集版本" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" header="模型评估闸门">
          <el-table :data="evaluations" size="small">
            <el-table-column label="模型" min-width="140"><template #default="{ row }">{{ row.model_name }} / {{ row.model_version }}</template></el-table-column>
            <el-table-column prop="split" label="分割" width="70" />
            <el-table-column prop="status" label="状态" width="80" />
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
.card-head { display: flex; justify-content: space-between; align-items: center; }
</style>
