<script setup lang="ts">
/**
 * 巡检回放（计划 0018 阶段 B）：按地块设施类型分两种模式。
 * 大棚模式按株回放（状态网格标出本次巡到的株 + 单株卡看全部照片）；大田模式保留地图、轨迹、长势和全部功能。
 * 问一问、AI 报告、农事建议是下面三个可折叠分区（展开状态记在本机）。各块在 components/patrol/ 里。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import PatrolAdvicePanel from '../components/patrol/PatrolAdvicePanel.vue'
import PatrolAskPanel from '../components/patrol/PatrolAskPanel.vue'
import PatrolFieldMode from '../components/patrol/PatrolFieldMode.vue'
import PatrolGreenhouseMode from '../components/patrol/PatrolGreenhouseMode.vue'
import PatrolReportPanel from '../components/patrol/PatrolReportPanel.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import { annotationsApi, capturePointsApi, fieldsApi, patrolsApi } from '../api'
import { errMsg } from '../api/http'
import { useBreadcrumb } from '../composables/useBreadcrumb'
import { fieldHomePath } from '../layouts/nav'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import {
  ANALYSIS_STATUS_LABELS, FACILITY_LABELS, isGreenhouse,
  type AnalysisSummary, type AnnotationSummary, type CapturePointFull, type FacilityType, type Field, type PatrolDetail,
} from '../types'
import { fieldClock } from '../utils/fieldTime'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()
const patrolId = Number(route.params.id)

const patrol = ref<PatrolDetail | null>(null)
const field = ref<Field | null>(null)
const points = ref<CapturePointFull[]>([])
const summary = ref<AnalysisSummary | null>(null)
const annSummary = ref<AnnotationSummary | null>(null)
const loading = ref(true)
const loadError = ref('')
/** 每次重新加载加一：回放和三个分区跟着重建，取到最新的分析、建议和报告 */
const version = ref(0)

const greenhouse = computed(() => (field.value ? isGreenhouse(field.value) : false))
const boundary = computed(() => (field.value?.boundary as { type: string; coordinates: number[][][] } | undefined) ?? null)

useBreadcrumb(() => [
  { label: '大棚与地块', to: '/fields' },
  ...(patrol.value ? [
    { label: field.value?.name ?? patrol.value.field_name ?? `地块 #${patrol.value.field_id}`, to: field.value ? fieldHomePath(field.value) : undefined },
    { label: '巡检记录', to: `/fields/${patrol.value.field_id}/patrols` },
  ] : []),
  { label: `巡检 #${patrolId}` },
])

async function loadAll() {
  loading.value = true
  try {
    const [detail, page] = await Promise.all([patrolsApi.get(patrolId), capturePointsApi.listByPatrol(patrolId)])
    // 地块要先到：设施类型决定用哪种回放，先画一种再换会闪一下、地图也会白建一次
    await Promise.all([loadField(detail.field_id), loadSummary(), loadAnnSummary()])
    patrol.value = detail
    points.value = page.items
    ui.setCurrentField(detail.field_id)
    loadError.value = ''
    version.value += 1
  } catch (e) {
    loadError.value = errMsg(e)
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  if (!Number.isInteger(patrolId) || patrolId <= 0) {
    void router.replace({ name: 'patrols' })
    return
  }
  void loadAll()
})

async function loadField(fieldId: number) {
  try { field.value = await fieldsApi.get(fieldId) } catch { /* 没有地块信息：按大田模式回放，只缺边界 */ }
}
async function loadSummary() {
  try { summary.value = await patrolsApi.summary(patrolId) } catch { /* 非关键 */ }
}
async function loadAnnSummary() {
  try { annSummary.value = await annotationsApi.summary(patrolId) } catch { /* 非关键 */ }
}

async function reanalyze() {
  try {
    await patrolsApi.analyze(patrolId)
    ElMessage.info('已调度后台重分析，完成后点「刷新」看新结果')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

/* ---------- 折叠分区：展开哪些记在本机 ---------- */
const PANELS_KEY = 'agriscout_patrol_panels'
function readPanels(): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(PANELS_KEY) ?? 'null')
    if (Array.isArray(saved)) return saved.filter((v): v is string => typeof v === 'string')
  } catch { /* 读不到就用默认 */ }
  return ['ask', 'report', 'advice']
}
const openPanels = ref<string[]>(readPanels())
watch(openPanels, (value) => {
  try { localStorage.setItem(PANELS_KEY, JSON.stringify(value)) } catch { /* 记不住不影响使用 */ }
})

function statusType(status: string): 'success' | 'danger' | 'warning' | 'info' {
  return status === 'done' ? 'success' : status === 'error' ? 'danger' : status === 'running' ? 'warning' : 'info'
}
const subtitle = computed(() => {
  const p = patrol.value
  if (!p) return ''
  const name = field.value?.name ?? p.field_name ?? `地块 #${p.field_id}`
  return `${name} · ${fieldClock(p.started_at)} 开始 · ${p.device_code ?? '未登记设备'}`
})
</script>

<template>
  <PageHeader :title="`巡检 #${patrolId}`" :subtitle="subtitle">
    <template #meta>
      <template v-if="patrol">
        <el-tag effect="plain" :type="greenhouse ? 'primary' : 'info'">
          {{ greenhouse ? '大棚 · 按株回放' : '大田 · 地图回放' }}
          <template v-if="field?.facility_type"> · {{ FACILITY_LABELS[field.facility_type as FacilityType] }}</template>
        </el-tag>
        <el-tag effect="plain" :type="statusType(patrol.analysis_status)">
          {{ ANALYSIS_STATUS_LABELS[patrol.analysis_status] ?? patrol.analysis_status }}
        </el-tag>
        <el-tag v-if="annSummary" effect="plain"
                :type="annSummary.points_total > 0 && annSummary.annotated_points >= annSummary.points_total ? 'success' : 'info'">
          已复核 {{ annSummary.annotated_points }}/{{ annSummary.points_total }} 点
        </el-tag>
        <span v-if="summary" class="muted text-13 stats">
          点位 {{ summary.total_points }} · 已分析 {{ summary.analyzed_points }}
          · 平均风险 {{ summary.avg_risk_score != null ? `${Math.round(summary.avg_risk_score * 100)}%` : '—' }}
          <template v-if="!greenhouse"> · 胁迫 {{ summary.stress_flagged_points }} 点</template>
        </span>
      </template>
    </template>
    <template #actions>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
      <el-button v-if="!auth.isViewer" @click="reanalyze">重分析</el-button>
    </template>
  </PageHeader>

  <EmptyState v-if="loadError && !patrol" title="这次巡检没取到" :description="loadError">
    <el-button @click="router.push('/patrols')">回巡检记录</el-button>
  </EmptyState>
  <el-skeleton v-else-if="!patrol" animated :rows="10" />
  <template v-else>
    <PatrolGreenhouseMode v-if="greenhouse" :key="`g${version}`" :patrol="patrol" :points="points" @annotated="loadAnnSummary" />
    <PatrolFieldMode v-else :key="`f${version}`" :patrol="patrol" :points="points" :boundary="boundary" @annotated="loadAnnSummary" />

    <el-collapse v-model="openPanels" class="panels">
      <PatrolAskPanel :patrol-id="patrol.id" />
      <PatrolReportPanel :key="`r${version}`" :patrol-id="patrol.id" />
      <PatrolAdvicePanel :key="`a${version}`" :patrol-id="patrol.id" :points="points" />
    </el-collapse>
  </template>
</template>

<style scoped>
.stats { font-variant-numeric: tabular-nums; }
.panels {
  margin-top: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  box-shadow: var(--shadow-1);
  overflow: hidden;
}
.panels :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 52px;
  padding: var(--space-2) 0 var(--space-2) var(--space-5);
  gap: var(--space-1);
  background: var(--bg-card);
  line-height: var(--lh-14);
}
.panels :deep(.el-collapse-item__title) { display: flex; flex: 1; flex-wrap: wrap; align-items: center; gap: var(--space-1) 0; min-width: 0; }
.panels :deep(.el-collapse-item__arrow) { margin: 0 var(--space-5) 0 var(--space-2); }
.panels :deep(.el-collapse-item__wrap) { background: var(--bg-card); }
.panels :deep(.el-collapse-item__content) { padding: 0 var(--space-5) var(--space-5); }
.panels :deep(.el-collapse-item:last-child .el-collapse-item__header),
.panels :deep(.el-collapse-item:last-child .el-collapse-item__wrap) { border-bottom: 0; }
</style>
