<script setup lang="ts">
/**
 * 单株时间线（计划 0014）：同一株每天一行，正面与叶背分列；补拍标第几次，质量不合格灰显并写原因。
 * 计划 0015 加「确认状态」：人工结论写成标注，挂在回看期内最近一张合格叶背图上，每株状态以最近一次人工结论为准。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import QualityBadge from '../components/ui/QualityBadge.vue'
import StateTag from '../components/ui/StateTag.vue'
import { annotationsApi, greenhouseApi, observationUnitsApi } from '../api'
import { errMsg } from '../api/http'
import { useBreadcrumb } from '../composables/useBreadcrumb'
import { fieldHomePath } from '../layouts/nav'
import { useAuthStore } from '../stores/auth'
import { useFieldsStore } from '../stores/fields'
import { useUiStore } from '../stores/ui'
import {
  ANNOTATION_LABELS,
  type AnnotationLabel, type ImageQuality, type PlantState, type TimelineDay, type TimelinePhoto, type UnitTimeline,
} from '../types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const fieldsStore = useFieldsStore()
const ui = useUiStore()
const unitId = Number(route.params.id)

const timeline = ref<UnitTimeline | null>(null)
const plantState = ref<PlantState | null>(null)
const loading = ref(false)
const days = ref(30)

// 面包屑能一键回到所属大棚（计划 0018 设计 3）
useBreadcrumb(() => {
  const unit = timeline.value?.unit
  const field = unit ? fieldsStore.byId.get(unit.field_id) : undefined
  return [
    { label: '大棚与地块', to: '/fields' },
    ...(unit ? [
      { label: field?.name ?? `地块 #${unit.field_id}`, to: field ? fieldHomePath(field) : undefined },
      { label: '株档案', to: `/fields/${unit.field_id}/units` },
    ] : []),
    { label: unit?.key ?? `株 #${unitId}` },
  ]
})

async function load() {
  loading.value = true
  try {
    timeline.value = await observationUnitsApi.timeline(unitId, days.value)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
  if (timeline.value) {
    ui.setCurrentField(timeline.value.unit.field_id)
    void fieldsStore.load().catch(() => { /* 面包屑退回显示地块编号 */ })
    await loadState(timeline.value.unit.field_id)
  }
}

/** 当前状态是按整块地算的（与计划同一口径），这里只取本株；拿不到不影响时间线 */
async function loadState(fieldId: number) {
  try {
    plantState.value = (await greenhouseApi.plantStates(fieldId)).find((s) => s.unit_id === unitId) ?? null
  } catch {
    plantState.value = null
  }
}
onMounted(() => {
  if (!Number.isInteger(unitId) || unitId <= 0) {
    void router.replace({ name: 'fields' })
    return
  }
  void load()
})

const LEVEL_TAG: Record<string, 'danger' | 'warning' | 'info'> = { high: 'danger', medium: 'warning', low: 'info' }
const LEVEL_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低', unknown: '不明' }
const FOLLOW_LABELS: Record<string, string> = {
  pending: '待随访',
  confirmed_positive: '确认阳性',
  confirmed_negative: '确认阴性',
  insufficient: '证据不足',
  intervened: '已处置',
  unknown: '未知',
}

/** 车端判断优先（拍摄当场的结论），没有再用平台按同一公式算的结果 */
function qualityOf(photo: TimelinePhoto): ImageQuality | null {
  return photo.view?.quality ?? photo.analysis?.image_quality ?? null
}
function badQuality(photo: TimelinePhoto): boolean {
  const q = qualityOf(photo)
  return q != null && q.ok === false
}
function sideOf(photo: TimelinePhoto): 'under' | 'upper' {
  return photo.view?.side === 'under' ? 'under' : 'upper'
}

interface Row {
  day: TimelineDay
  upper: TimelinePhoto[]
  under: TimelinePhoto[]
  maxRisk: number | null
  topPrediction: TimelineDay['predictions'][number] | null
}
const rows = computed<Row[]>(() =>
  (timeline.value?.days ?? [])
    .slice()
    .reverse()
    .map((day) => {
      const risks = day.photos.map((p) => p.analysis?.risk_score).filter((v): v is number => v != null)
      const topPrediction = day.predictions.reduce<Row['topPrediction']>(
        (best, p) => (best == null || p.probability > best.probability ? p : best),
        null,
      )
      return {
        day,
        upper: day.photos.filter((p) => sideOf(p) === 'upper'),
        under: day.photos.filter((p) => sideOf(p) === 'under'),
        maxRisk: risks.length ? Math.max(...risks) : null,
        topPrediction,
      }
    }),
)

/** 与后端 field_date（UTC+8）同一口径：行按田间日期分组，时刻也按田间时区显示，不随浏览器时区漂移 */
function timeText(iso: string): string {
  return new Date(iso).toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai',
  })
}
function annotationText(label: string): string {
  return ANNOTATION_LABELS[label as AnnotationLabel] ?? label
}

/* ---------- 确认状态（计划 0015） ---------- */
const CONFIRM_OPTIONS: { label: AnnotationLabel; text: string }[] = [
  { label: 'normal', text: '健康' },
  { label: 'downy_mildew_early', text: '早期' },
  { label: 'downy_mildew_symptomatic', text: '明显' },
  { label: 'other', text: '其他' },
]
const confirmLabel = ref<AnnotationLabel | ''>('')
const confirmNote = ref('')
const annotator = ref(auth.user?.display_name ?? '')
const confirming = ref(false)

/** 与后端 greenhouse_plans._accepted 同口径：车端 accepted 优先，没有再看平台测的质量 */
function accepted(photo: TimelinePhoto): boolean | null {
  if (typeof photo.view?.accepted === 'boolean') return photo.view.accepted
  const ok = photo.analysis?.image_quality?.ok
  return typeof ok === 'boolean' ? ok : null
}
const targetPhoto = computed<TimelinePhoto | null>(() =>
  (timeline.value?.days ?? [])
    .flatMap((d) => d.photos)
    .filter((p) => sideOf(p) === 'under' && accepted(p) === true)
    .reduce<TimelinePhoto | null>(
      (best, p) => (best == null || Date.parse(p.captured_at) > Date.parse(best.captured_at) ? p : best),
      null,
    ),
)
const canConfirm = computed(() => !auth.isViewer && targetPhoto.value != null)
const confirmHint = computed(() => {
  if (auth.isViewer) return '只读账号不能确认'
  const photo = targetPhoto.value
  if (!photo) return `回看期内没有合格的叶背图，可加长回看或先补拍`
  const day = new Date(photo.captured_at).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' })
  return `挂到 ${day} ${timeText(photo.captured_at)} 的叶背图`
})
function stateSource(state: PlantState): string {
  if (state.source === 'human') {
    const at = state.reviewed_at
      ? new Date(state.reviewed_at).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' })
      : ''
    return `人工确认 ${at}`.trim()
  }
  if (state.source === 'model') return `模型占位 ${state.model_score?.toFixed(2) ?? '—'}，不是诊断`
  return '还没有合格叶背图'
}

async function submitConfirm() {
  const photo = targetPhoto.value
  const label = confirmLabel.value
  if (!photo || !label) return
  const name = annotator.value.trim()
  if (!name) {
    ElMessage.warning('请填写确认人')
    return
  }
  confirming.value = true
  try {
    await annotationsApi.submit(photo.capture_point_id, { label, annotator_name: name, note: confirmNote.value.trim() || null })
    ElMessage.success(`已确认为「${CONFIRM_OPTIONS.find((o) => o.label === label)?.text}」`)
    confirmLabel.value = ''
    confirmNote.value = ''
    void ui.refreshConfirmCount(true)
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    confirming.value = false
  }
}
</script>

<template>
  <div class="head">
    <el-button :icon="ArrowLeft" text @click="timeline ? router.push({ name: 'field-units', params: { id: timeline.unit.field_id } }) : router.back()">
      株档案
    </el-button>
    <span class="title">{{ timeline?.unit.key ?? `株 #${unitId}` }} · 单株时间线</span>
    <span v-if="timeline" class="meta">
      <template v-if="timeline.unit.row_no != null">第 {{ timeline.unit.row_no }} 垄 · 第 {{ timeline.unit.position_no }} 株</template>
      <template v-else>自定义株号</template>
      <template v-if="timeline.unit.tag_code"> · 标签 {{ timeline.unit.tag_code }}</template>
    </span>
    <span class="spacer" />
    回看
    <el-select v-model="days" size="small" style="width: 96px" @change="load">
      <el-option :value="7" label="7 天" />
      <el-option :value="30" label="30 天" />
      <el-option :value="90" label="90 天" />
    </el-select>
    <el-button :icon="Refresh" circle size="small" title="刷新" @click="load" />
  </div>

  <div class="confirm">
    <span class="confirm-title">确认状态</span>
    <template v-if="plantState">
      当前
      <StateTag :state="plantState.state" size="small" />
      <span class="sub">{{ stateSource(plantState) }}</span>
    </template>
    <span class="divider" />
    <el-radio-group v-model="confirmLabel" size="small" :disabled="!canConfirm">
      <el-radio-button v-for="o in CONFIRM_OPTIONS" :key="o.label" :value="o.label">{{ o.text }}</el-radio-button>
    </el-radio-group>
    <el-input v-model="annotator" size="small" placeholder="确认人" style="width: 110px" :disabled="!canConfirm" />
    <el-input v-model="confirmNote" size="small" placeholder="备注（可选）" style="width: 180px" :disabled="!canConfirm" />
    <el-button type="primary" size="small" :loading="confirming" :disabled="!canConfirm || !confirmLabel" @click="submitConfirm">
      提交
    </el-button>
    <span class="sub">{{ confirmHint }}</span>
  </div>

  <el-table :data="rows" v-loading="loading" border size="small" empty-text="这株在回看期内还没有照片">
    <el-table-column label="日期" width="110">
      <template #default="{ row }">{{ row.day.field_date }}</template>
    </el-table-column>
    <el-table-column v-for="side in (['upper', 'under'] as const)" :key="side" :label="side === 'upper' ? '正面' : '叶背'" min-width="240">
      <template #default="{ row }">
        <div class="thumbs">
          <div v-for="photo in row[side]" :key="photo.capture_point_id" class="thumb" :class="{ bad: badQuality(photo) }">
            <el-image
              v-if="photo.photo_url"
              :src="photo.photo_url"
              :preview-src-list="[photo.photo_url]"
              fit="cover"
              preview-teleported
            />
            <div v-else class="no-photo">无照片</div>
            <div class="caption">
              {{ timeText(photo.captured_at) }}
              <span v-if="photo.view?.pitch_deg != null"> · {{ photo.view.pitch_deg }}°</span>
              <el-tag v-if="(photo.view?.attempt ?? 1) > 1" size="small" effect="plain" type="info">第 {{ photo.view?.attempt }} 次</el-tag>
            </div>
            <QualityBadge :quality="qualityOf(photo)" class="quality" />
          </div>
          <span v-if="!row[side].length" class="empty">—</span>
        </div>
      </template>
    </el-table-column>
    <el-table-column label="风险分" width="80" align="center">
      <template #default="{ row }">{{ row.maxRisk == null ? '—' : row.maxRisk.toFixed(2) }}</template>
    </el-table-column>
    <el-table-column label="预测 / 随访" width="170">
      <template #default="{ row }">
        <template v-if="row.topPrediction">
          <el-tag :type="LEVEL_TAG[row.topPrediction.level] ?? 'info'" size="small" effect="plain">
            {{ LEVEL_LABELS[row.topPrediction.level] ?? row.topPrediction.level }} {{ (row.topPrediction.probability * 100).toFixed(0) }}%
          </el-tag>
          <div class="sub">{{ row.topPrediction.follow_up_status ? FOLLOW_LABELS[row.topPrediction.follow_up_status] ?? row.topPrediction.follow_up_status : '未随访' }}</div>
        </template>
        <span v-else class="empty">—</span>
      </template>
    </el-table-column>
    <el-table-column label="人工复核" width="140">
      <template #default="{ row }">
        <div v-for="a in row.day.annotations" :key="a.id" class="sub">{{ annotationText(a.label) }} · {{ a.annotator_name }}</div>
        <span v-if="!row.day.annotations.length" class="empty">—</span>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-size: 13px; color: var(--el-text-color-regular); }
.title { font-size: 16px; font-weight: 600; color: var(--el-text-color-primary); }
.meta { color: var(--el-text-color-secondary); }
.spacer { flex: 1; }
.thumbs { display: flex; flex-wrap: wrap; gap: 8px; }
.thumb { width: 108px; }
.thumb :deep(.el-image), .no-photo { width: 108px; height: 81px; border-radius: 4px; display: block; background: var(--el-fill-color-light); }
.no-photo { display: flex; align-items: center; justify-content: center; font-size: 12px; color: var(--el-text-color-placeholder); }
.thumb.bad :deep(.el-image) { filter: grayscale(1); opacity: 0.55; }
.caption { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.quality { margin-top: 2px; }
.sub { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.empty { color: var(--el-text-color-placeholder); }
.confirm { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; padding: 8px 12px; font-size: 13px;
  border: 1px solid var(--el-border-color-lighter); border-radius: 4px; color: var(--el-text-color-regular); }
.confirm-title { font-weight: 600; color: var(--el-text-color-primary); }
.confirm .sub { margin-top: 0; }
.divider { width: 1px; height: 16px; background: var(--el-border-color); margin: 0 4px; }
</style>
