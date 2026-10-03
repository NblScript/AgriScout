<script setup lang="ts">
/** 单株时间线（计划 0014）：同一株每天一行，正面与叶背分列；补拍标第几次，质量不合格灰显并写原因。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { observationUnitsApi } from '../api'
import { errMsg } from '../api/http'
import { ANNOTATION_LABELS, type AnnotationLabel, type ImageQuality, type TimelineDay, type TimelinePhoto, type UnitTimeline } from '../types'

const route = useRoute()
const router = useRouter()
const unitId = Number(route.params.id)

const timeline = ref<UnitTimeline | null>(null)
const loading = ref(false)
const days = ref(30)

async function load() {
  loading.value = true
  try {
    timeline.value = await observationUnitsApi.timeline(unitId, days.value)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  if (!Number.isInteger(unitId) || unitId <= 0) {
    void router.replace({ name: 'fields' })
    return
  }
  void load()
})

const REASON_LABELS: Record<string, string> = {
  blurry: '模糊',
  overexposed: '过曝',
  underexposed: '欠曝',
  backlit: '逆光',
}
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
function reasonText(photo: TimelinePhoto): string {
  const q = qualityOf(photo)
  return (q?.reasons ?? []).map((r) => REASON_LABELS[r] ?? r).join('、')
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
            <div v-if="badQuality(photo)" class="reason">不合格：{{ reasonText(photo) }}</div>
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
.reason { font-size: 12px; color: var(--el-color-danger); }
.sub { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.empty { color: var(--el-text-color-placeholder); }
</style>
