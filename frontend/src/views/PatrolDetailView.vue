<script setup lang="ts">
/** 巡检回放：地图回放 + 时间轴 + 人工复核 + 建议面板。亮色专业工具风。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, CaretBottom, CaretTop, Refresh, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import MapCanvas from '../components/MapCanvas.vue'
import EChart from '../components/EChart.vue'
import { advicesApi, annotationsApi, capturePointsApi, fieldsApi, patrolsApi } from '../api'
import {
  ADVICE_STATUS_LABELS,
  ANNOTATION_LABELS,
  ANNOTATION_TAG_TYPES,
  VIGOR_COLORS,
  type Advice,
  type AdviceStatus,
  type AnalysisSummary,
  type Annotation,
  type AnnotationLabel,
  type AnnotationSummary,
  type CapturePointFull,
  type PatrolDetail,
} from '../types'

const route = useRoute()
const router = useRouter()
const patrolId = Number(route.params.id)

const patrol = ref<PatrolDetail | null>(null)
const points = ref<CapturePointFull[]>([])
const advices = ref<Advice[]>([])
const summary = ref<AnalysisSummary | null>(null)
const fieldBoundary = ref<{ type: string; coordinates: number[][][] } | null>(null)
const loading = ref(true)

/* ---------- 时间轴与选中点 ---------- */
const currentIndex = ref(0)
const playing = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const currentPoint = computed<CapturePointFull | null>(
  () => points.value[currentIndex.value] ?? null,
)

function selectByPointId(pointId: number) {
  const idx = points.value.findIndex((p) => p.id === pointId)
  if (idx >= 0) {
    currentIndex.value = idx
    stopPlay()
  }
}

function togglePlay() {
  if (!points.value.length) return
  if (playing.value) return stopPlay()
  playing.value = true
  if (currentIndex.value >= points.value.length - 1) currentIndex.value = 0
  timer = setInterval(() => {
    if (currentIndex.value < points.value.length - 1) currentIndex.value += 1
    else stopPlay()
  }, 200)
}

function stopPlay() {
  playing.value = false
  if (timer) clearInterval(timer)
  timer = null
}
onBeforeUnmount(stopPlay)

function step(delta: number) {
  stopPlay()
  const next = currentIndex.value + delta
  if (next >= 0 && next < points.value.length) currentIndex.value = next
}

/* ---------- 数据加载 ---------- */
async function loadAll() {
  loading.value = true
  try {
    patrol.value = await patrolsApi.get(patrolId)
    const page = await capturePointsApi.listByPatrol(patrolId)
    points.value = page.items
    await Promise.all([loadAdvices(), loadSummary(), loadFieldBoundary(), loadAnnSummary()])
    currentIndex.value = points.value.length ? Math.min(currentIndex.value, points.value.length - 1) : 0
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}
onMounted(loadAll)

async function loadFieldBoundary() {
  if (!patrol.value) return
  try {
    const field = await fieldsApi.get(patrol.value.field_id)
    fieldBoundary.value = field.boundary as { type: string; coordinates: number[][][] }
  } catch { /* 边界缺失仅影响底图多边形 */ }
}

async function loadSummary() {
  try { summary.value = await patrolsApi.summary(patrolId) } catch { /* 非关键 */ }
}

async function loadAdvices() {
  try {
    advices.value = (await advicesApi.list(patrolId)).items
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

/* ---------- 建议操作 ---------- */
const adviceFilter = ref<AdviceStatus | ''>('')
const filteredAdvices = computed(() =>
  adviceFilter.value ? advices.value.filter((a) => a.status === adviceFilter.value) : advices.value,
)
const seqByPointId = computed(() => new Map(points.value.map((p) => [p.id, p.seq])))

async function decide(advice: Advice, status: Exclude<AdviceStatus, 'suggested'>) {
  try {
    const updated = await advicesApi.setStatus(advice.id, status)
    const idx = advices.value.findIndex((a) => a.id === updated.id)
    if (idx >= 0) advices.value[idx] = updated
    ElMessage.success(`建议已${ADVICE_STATUS_LABELS[status]}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function regenerateAdvices() {
  try {
    await ElMessageBox.confirm(
      '重新生成会清理“待处理”建议并按当前规则重算；已采纳/驳回的记录保留。继续？',
      '重新生成建议',
      { type: 'warning' },
    )
  } catch { return }
  try {
    const stats = await advicesApi.generate(patrolId)
    ElMessage.success(`已重算：新增 ${stats.created} 条（保护决策 ${stats.skipped_decided} 条）`)
    await loadAdvices()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function reanalyze() {
  try {
    await patrolsApi.analyze(patrolId)
    ElMessage.info('已调度后台重分析，完成后刷新页面查看新结果')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

/* ---------- 人工复核标注（回流闭环） ---------- */
const ANNOTATOR_KEY = 'agriscout_annotator'
const annotations = ref<Annotation[]>([])
const annSummary = ref<AnnotationSummary | null>(null)
const annLabel = ref<AnnotationLabel>('normal')
const annNote = ref('')
const annotator = ref(localStorage.getItem(ANNOTATOR_KEY) ?? '')
const annotating = ref(false)

async function loadPointAnnotations() {
  annotations.value = []
  if (!currentPoint.value) return
  try {
    annotations.value = await annotationsApi.listByPoint(currentPoint.value.id)
  } catch { /* 非关键，不打断回放 */ }
}

async function loadAnnSummary() {
  try { annSummary.value = await annotationsApi.summary(patrolId) } catch { /* 非关键 */ }
}

watch(() => currentPoint.value?.id, loadPointAnnotations)

async function submitAnnotation() {
  const point = currentPoint.value
  if (!point) return
  const name = annotator.value.trim()
  if (!name) {
    ElMessage.warning('请先填写标注人姓名（将作为数据集归属）')
    return
  }
  annotating.value = true
  localStorage.setItem(ANNOTATOR_KEY, name)
  try {
    const saved = await annotationsApi.submit(point.id, {
      label: annLabel.value,
      annotator_name: name,
      note: annNote.value.trim() || null,
    })
    const existed = annotations.value.some((a) => a.id === saved.id)
    const idx = annotations.value.findIndex((a) => a.id === saved.id)
    if (idx >= 0) annotations.value[idx] = saved
    else annotations.value.push(saved)
    ElMessage.success(existed ? '该标签已更新复核结论' : '复核结果已入库')
    annNote.value = ''
    await loadAnnSummary()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    annotating.value = false
  }
}

async function removeAnnotation(ann: Annotation) {
  try {
    await annotationsApi.remove(ann.id)
    annotations.value = annotations.value.filter((a) => a.id !== ann.id)
    await loadAnnSummary()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

/* ---------- 展示辅助 ---------- */
function vigorStars(level: number | null): string {
  if (!level) return '—'
  return '★★★★★'.slice(0, level) + '☆☆☆☆☆'.slice(0, 5 - level)
}
function pct(v: number | null): number {
  return v == null ? 0 : Math.round(v * 100)
}
const stageName = computed(() =>
  (currentPoint.value?.analysis?.growth_stage?.name as string | undefined) ?? null,
)

/* ---------- 沿线天气曲线 ---------- */
const AXIS = {
  axisLine: { lineStyle: { color: '#d7dfd8' } },
  axisLabel: { color: '#7a8a7e', fontSize: 9 },
  splitLine: { lineStyle: { color: '#edf1ed' } },
}
const weatherOption = computed<EChartsOption>(() => {
  const pts = points.value
  return {
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['气温', '土湿'], top: 0, right: 0,
      textStyle: { color: '#7a8a7e', fontSize: 10 }, itemWidth: 12, itemHeight: 8,
    },
    grid: { left: 32, right: 34, top: 22, bottom: 18 },
    xAxis: {
      type: 'category', boundaryGap: false, ...AXIS,
      data: pts.map((p) => `${p.distance_m.toFixed(1)}m`),
    },
    yAxis: [
      { type: 'value', ...AXIS },
      { type: 'value', ...AXIS, splitLine: { show: false } },
    ],
    series: [
      {
        name: '气温', type: 'line', smooth: true, showSymbol: false, sampling: 'lttb',
        lineStyle: { color: '#d97706', width: 1.5 },
        areaStyle: { color: 'rgba(217,119,6,0.06)' },
        data: pts.map((p) => p.weather?.temp_c ?? null),
        markLine: currentIndex.value < pts.length
          ? {
              symbol: 'none', label: { show: false },
              lineStyle: { color: '#16a34a', width: 1 },
              data: [{ xAxis: currentIndex.value }],
            }
          : undefined,
      },
      {
        name: '土湿', type: 'line', smooth: true, showSymbol: false, yAxisIndex: 1, sampling: 'lttb',
        lineStyle: { color: '#2563eb', width: 1.5 },
        areaStyle: { color: 'rgba(37,99,235,0.06)' },
        data: pts.map((p) => p.weather?.soil_moisture_pct ?? null),
      },
    ],
  }
})
</script>

<template>
  <div v-loading="loading">
    <!-- 头部信息 -->
    <div class="head" v-if="patrol">
      <el-button :icon="ArrowLeft" circle @click="router.push('/patrols')" />
      <h3 class="title">巡检 #{{ patrol.id }} · {{ patrol.field_name ?? `地块#${patrol.field_id}` }}</h3>
      <el-tag effect="plain">{{ patrol.device_code ?? '未知设备' }}</el-tag>
      <el-tag :type="patrol.analysis_status === 'done' ? 'success' : 'warning'" effect="plain">
        分析{{ patrol.analysis_status }}
      </el-tag>
      <el-tag
        v-if="annSummary"
        :type="annSummary.annotated_points >= annSummary.points_total && annSummary.points_total > 0 ? 'success' : 'info'"
        effect="plain"
      >
        已复核 {{ annSummary.annotated_points }}/{{ annSummary.points_total }} 点
      </el-tag>
      <span class="meta" v-if="summary">
        点位 {{ summary.total_points }} · 已分析 {{ summary.analyzed_points }}
        · NDVI代理 {{ summary.avg_ndvi ?? '—' }} · 平均风险 {{ summary.avg_risk_score ?? '—' }}
        · 胁迫 {{ summary.stress_flagged_points }} 点
      </span>
      <div class="actions">
        <el-button size="small" :icon="Refresh" @click="reanalyze">重分析</el-button>
        <el-button size="small" type="primary" plain @click="regenerateAdvices">重算建议</el-button>
      </div>
    </div>

    <!-- 地图 + 详情卡 -->
    <el-row :gutter="12">
      <el-col :span="15">
        <div class="panel map-panel">
          <MapCanvas
            theme="light"
            :boundary="fieldBoundary"
            :track="patrol?.track ?? null"
            :points="points"
            :selected-index="currentIndex"
            @select="selectByPointId"
          />
          <div class="legend">
            <span v-for="(c, lv) in VIGOR_COLORS" :key="lv" class="lg"><i :style="{ background: c }" />长势{{ lv }}</span>
            <span class="lg"><i style="background:#9e9e9e" />未分析</span>
            <span class="lg"><i style="border:2px solid #fbbf24;background:#fff" />胁迫检出</span>
          </div>
        </div>
        <!-- 时间轴 -->
        <div class="panel timeline">
          <el-button size="small" :icon="CaretTop" :disabled="!points.length" @click="step(-1)" />
          <el-button
            size="small" type="primary"
            :icon="playing ? VideoPause : VideoPlay"
            :disabled="!points.length"
            @click="togglePlay"
          >
            {{ playing ? '暂停' : '播放' }}
          </el-button>
          <el-button size="small" :icon="CaretBottom" :disabled="!points.length" @click="step(1)" />
          <el-slider
            v-model="currentIndex"
            :min="0" :max="Math.max(points.length - 1, 0)"
            :disabled="!points.length" style="flex:1; margin: 0 14px"
            :show-tooltip="false"
          />
          <span class="tl-label">
            {{ currentPoint ? `#${currentPoint.seq} / ${points.length - 1}` : '无数据' }}
          </span>
        </div>
      </el-col>

      <!-- 选中点详情卡 -->
      <el-col :span="9">
        <div class="panel detail-card">
          <template v-if="currentPoint">
            <h4>采样点 #{{ currentPoint.seq }}（里程 {{ currentPoint.distance_m }}m）</h4>
            <el-image
              v-if="currentPoint.photo_url" :src="currentPoint.photo_url"
              :preview-src-list="[currentPoint.photo_url]"
              :initial-index="0" preview-teleported hide-on-click-modal
              class="photo" fit="cover" alt="采样照片（点击放大）"
            />
            <p v-else class="dim">该点无照片</p>

            <template v-if="currentPoint.analysis">
              <div class="kv-row">
                <span>生育期</span><b>{{ stageName ?? '—' }}</b>
              </div>
              <div class="kv-row">
                <span>长势等级</span>
                <b :style="{ color: VIGOR_COLORS[currentPoint.analysis.vigor_level ?? 0] || '#999' }">
                  {{ vigorStars(currentPoint.analysis.vigor_level) }}
                </b>
              </div>
              <div class="kv-row">
                <span>NDVI代理</span><b>{{ currentPoint.analysis.ndvi ?? '—' }}</b>
              </div>
              <div class="kv-row">
                <span>风险分</span>
                <el-progress
                  style="flex:1"
                  :percentage="pct(currentPoint.analysis.risk_score)"
                  :color="pct(currentPoint.analysis.risk_score) > 60 ? '#dc2626' : '#16a34a'"
                  :stroke-width="10"
                />
              </div>
              <div v-if="currentPoint.analysis.disease_detections?.length" class="stress-box">
                <el-tag v-for="(d, i) in currentPoint.analysis.disease_detections" :key="i" type="warning" effect="plain">
                  ⚠ {{ d.label ?? d.type }}
                </el-tag>
              </div>
            </template>
            <p v-else class="dim">该点未产出分析结果</p>

            <el-divider />
            <div class="ann-box">
              <h5>人工复核 <span class="dim">（结论进入训练数据集）</span></h5>
              <div v-if="annotations.length" class="ann-tags">
                <el-tag
                  v-for="a in annotations" :key="a.id"
                  :type="ANNOTATION_TAG_TYPES[a.label as AnnotationLabel] ?? 'info'"
                  closable @close="removeAnnotation(a)"
                >
                  {{ ANNOTATION_LABELS[a.label as AnnotationLabel] ?? a.label }} · {{ a.annotator_name }}
                </el-tag>
              </div>
              <div class="ann-form">
                <el-select
                  v-model="annLabel" size="small" style="width: 118px" :teleported="false"
                >
                  <el-option
                    v-for="(text, key) in ANNOTATION_LABELS"
                    :key="key" :value="key" :label="text"
                  />
                </el-select>
                <el-input
                  v-model="annotator" size="small" style="width: 96px"
                  placeholder="标注人" maxlength="80"
                />
                <el-input
                  v-model="annNote" size="small" style="flex: 1; min-width: 120px"
                  placeholder="备注（可选）" maxlength="500"
                />
                <el-button size="small" type="primary" :loading="annotating" @click="submitAnnotation">
                  提交复核
                </el-button>
              </div>
            </div>

            <el-divider />
            <div class="wx-chart">
              <h5>沿线环境曲线 <span class="dim">（绿线为当前点）</span></h5>
              <EChart :option="weatherOption" class="wx-echart" />
            </div>
            <p class="dim time">{{ new Date(currentPoint.captured_at).toLocaleString('zh-CN') }}</p>
          </template>
          <p v-else class="dim">暂无采样点数据</p>
        </div>
      </el-col>
    </el-row>

    <!-- 建议面板 -->
    <div class="panel advices-panel">
      <div class="adv-head">
        <h4>农事建议（可溯源）</h4>
        <el-radio-group v-model="adviceFilter" size="small">
          <el-radio-button value="">全部 {{ advices.length }}</el-radio-button>
          <el-radio-button value="suggested">
            待处理 {{ advices.filter(a => a.status === 'suggested').length }}
          </el-radio-button>
          <el-radio-button value="accepted">已采纳</el-radio-button>
          <el-radio-button value="rejected">已驳回</el-radio-button>
        </el-radio-group>
      </div>
      <el-table :data="filteredAdvices" border size="small" max-height="360">
        <el-table-column label="点" width="64">
          <template #default="{ row }">{{ row.capture_point_id != null ? `#${seqByPointId.get(row.capture_point_id) ?? '?'}` : '—' }}</template>
        </el-table-column>
        <el-table-column label="优先级" width="90">
          <template #default="{ row }">
            <el-tag :type="row.priority === 'high' ? 'danger' : row.priority === 'medium' ? 'warning' : 'info'" size="small" effect="plain">
              {{ row.priority }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="建议内容" min-width="320" show-overflow-tooltip />
        <el-table-column label="规则依据" width="150">
          <template #default="{ row }">
            <el-tooltip placement="top">
              <template #content>
                规则 {{ row.rule_snapshot.rule_key }} v{{ row.rule_snapshot.version }}<br>
                层级：{{ row.rule_snapshot.tier }} · 条件：{{ JSON.stringify(row.rule_snapshot.condition) }}<br>
                出处：{{ row.rule_snapshot.source || '—' }}
              </template>
              <span class="rule-link">{{ row.rule_snapshot.rule_key }} v{{ row.rule_snapshot.version }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'accepted' ? 'success' : row.status === 'rejected' ? 'danger' : 'primary'" effect="plain">
              {{ ADVICE_STATUS_LABELS[row.status as AdviceStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'suggested'">
              <el-button size="small" type="success" plain @click="decide(row, 'accepted')">采纳</el-button>
              <el-button size="small" type="danger" plain @click="decide(row, 'rejected')">驳回</el-button>
            </template>
            <span v-else class="dim">已决策</span>
          </template>
        </el-table-column>
        <template #empty>暂无建议——点击右上角「重算建议」或先完成分析</template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.title { margin-right: 4px; }
.meta { font-size: 12px; color: #6b7a6b; }
.actions { margin-left: auto; }
.panel {
  background: #fff;
  border: 1px solid #e2e8e2;
  border-radius: 10px;
  padding: 12px;
}
.map-panel {
  position: relative;
  height: 430px;
  overflow: hidden;
}
.legend {
  position: absolute;
  z-index: 500;
  bottom: 8px;
  left: 10px;
  background: rgba(255, 255, 255, 0.92);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  color: #4a5d4e;
  display: flex;
  gap: 8px;
  align-items: center;
}
.lg i {
  display: inline-block;
  width: 9px; height: 9px;
  border-radius: 50%;
  margin-right: 3px;
  vertical-align: -1px;
}
.timeline {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.tl-label { min-width: 84px; text-align: right; font-size: 12px; color: #6b7a6b; }
.detail-card { max-height: 505px; overflow: auto; }
.detail-card h4 { margin-bottom: 10px; }
.detail-card h5 { font-size: 13px; margin-bottom: 8px; color: #1f2d1f; }
.photo {
  width: 100%;
  border-radius: 8px;
  margin-bottom: 10px;
  max-height: 190px;
}
.kv-row { display: flex; align-items: center; gap: 10px; margin: 7px 0; }
.kv-row > span { width: 68px; font-size: 13px; color: #6b7a6b; }
.stress-box { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
.wx-chart h5 { margin-bottom: 4px; }
.wx-echart { height: 150px; }
.dim { color: #9aa79a; font-size: 13px; }
.time { margin-top: 8px; }

/* 复核区块 */
.ann-box h5 { margin-bottom: 8px; }
.ann-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.ann-form { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }

.advices-panel { margin-top: 12px; }
.adv-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.rule-link {
  cursor: help;
  border-bottom: 1px dashed #90a4ae;
  font-size: 12px;
  color: #546e7a;
}
</style>
