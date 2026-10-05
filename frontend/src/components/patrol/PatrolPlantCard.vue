<script setup lang="ts">
/**
 * 巡检回放 · 大棚模式的单株卡：这一株本次的全部照片按正面 / 叶背、第几次拍排开（带质量徽标和不合格原因），
 * 点一张看大图、病斑框、分析结果和人工复核；链到单株时间线。不显示长势、NDVI、生育期（大棚不用这套）。
 */
import { computed, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import PhotoThumb from '../plant/PhotoThumb.vue'
import QualityBadge from '../ui/QualityBadge.vue'
import StateTag from '../ui/StateTag.vue'
import PatrolDetections from './PatrolDetections.vue'
import PatrolPointPhoto from './PatrolPointPhoto.vue'
import PointReviewBox from './PointReviewBox.vue'
import { PLANT_SOURCE_LABELS, type CapturePointFull, type PlantState } from '../../types'
import { fieldClock } from '../../utils/fieldTime'
import type { PlantVisit } from '../../utils/patrolVisits'
import { isAccepted, photoSide, pointAsPhoto, pointQuality, type PhotoSide } from '../../utils/plantPhotos'

const props = defineProps<{ visit: PlantVisit; state: PlantState | null }>()
const emit = defineEmits<{ annotated: [] }>()

const SIDES: { side: PhotoSide; label: string }[] = [
  { side: 'under', label: '叶背' },
  { side: 'upper', label: '正面' },
]
const groups = computed(() => SIDES.map(({ side, label }) => {
  const points = props.visit.points
    .filter((p) => photoSide(p.view) === side)
    .sort((a, b) => (a.view?.attempt ?? 1) - (b.view?.attempt ?? 1) || Date.parse(a.captured_at) - Date.parse(b.captured_at))
  const ok = points.filter((p) => accepted(p) === true).length
  return { side, label, points, ok }
}).filter((g) => g.points.length))

function accepted(point: CapturePointFull): boolean | null {
  return isAccepted(point.view, pointQuality(point))
}

/** 默认选最后一张合格叶背（确认看的就是它），没有就选最后拍的那张 */
function defaultPoint(points: CapturePointFull[]): number | null {
  const under = points.filter((p) => photoSide(p.view) === 'under' && accepted(p) === true)
  const pick = under.at(-1) ?? points.at(-1)
  return pick?.id ?? null
}
const selectedId = ref<number | null>(null)
watch(() => props.visit.key, () => { selectedId.value = defaultPoint(props.visit.points) }, { immediate: true })
const point = computed(() => props.visit.points.find((p) => p.id === selectedId.value) ?? null)
const analysis = computed(() => point.value?.analysis ?? null)
const risk = computed(() => (analysis.value?.risk_score == null ? null : Math.round(analysis.value.risk_score * 100)))

const stateBasis = computed(() => {
  const s = props.state
  if (!s) return ''
  return s.source === 'model' ? `${PLANT_SOURCE_LABELS.model} ${s.model_score?.toFixed(2) ?? '—'}` : PLANT_SOURCE_LABELS[s.source]
})
function viewText(p: CapturePointFull): string {
  const v = p.view
  if (!v) return '没有视角记录（协议 v1）'
  const parts = [photoSide(v) === 'under' ? '叶背' : v.side === 'upper' ? '正面' : '视角不明', `第 ${v.attempt} 次`]
  if (v.pitch_deg != null) parts.push(`俯仰 ${v.pitch_deg}°`)
  if (v.height_m != null) parts.push(`离地 ${v.height_m} m`)
  if (v.fill_light != null) parts.push(v.fill_light ? '补光' : '未补光')
  return parts.join(' · ')
}
</script>

<template>
  <div class="plant-card">
    <header class="head">
      <div class="title">
        <router-link v-if="visit.unitId != null" :to="`/units/${visit.unitId}`" class="key">{{ visit.label }}</router-link>
        <span v-else class="key">{{ visit.label }}</span>
        <StateTag v-if="state" :state="state.state" size="small" />
        <span v-if="state" class="muted text-12">当前 · {{ stateBasis }}</span>
      </div>
      <router-link v-if="visit.unitId != null" :to="`/units/${visit.unitId}`" class="more">
        单株时间线<el-icon><ArrowRight /></el-icon>
      </router-link>
      <span v-else class="muted text-12">这个点没关联到株（协议 v1 或株号解析失败）</span>
    </header>

    <section v-for="g in groups" :key="g.side" class="group">
      <div class="group-head">
        <span class="group-label">{{ g.label }}</span>
        <span class="muted text-12">{{ g.points.length }} 张 · 合格 {{ g.ok }}</span>
      </div>
      <div class="thumbs">
        <PhotoThumb v-for="p in g.points" :key="p.id" :photo="pointAsPhoto(p)" selectable :selected="p.id === selectedId"
                    @select="selectedId = p.id" />
      </div>
    </section>

    <div v-if="point" class="detail">
      <div class="detail-head">
        <span class="text-13">采样点 #{{ point.seq }} · {{ fieldClock(point.captured_at) }}</span>
        <QualityBadge :quality="pointQuality(point)" :accepted="accepted(point)" />
      </div>
      <PatrolPointPhoto :point="point" fill :gray="accepted(point) === false" />
      <p class="muted text-12 view">{{ viewText(point) }}</p>
      <dl v-if="analysis" class="kv">
        <div>
          <dt>风险分</dt>
          <dd><b class="num">{{ risk == null ? '—' : `${risk}%` }}</b><span class="muted text-12">模型占位分数，不是诊断</span></dd>
        </div>
        <div><dt>分析器</dt><dd class="text-13">{{ analysis.analyzer_version }}</dd></div>
      </dl>
      <p v-else class="muted text-13 none">这张还没有分析结果</p>
      <PatrolDetections :detections="analysis?.disease_detections ?? []" />
      <el-divider />
      <PointReviewBox :point-id="point.id" @changed="emit('annotated')" />
    </div>
  </div>
</template>

<style scoped>
.plant-card { display: flex; flex-direction: column; gap: var(--space-4); }
.head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); }
.title { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); min-width: 0; }
.key { font-family: var(--font-mono); font-size: var(--fs-16); font-weight: var(--fw-semibold); color: var(--text-primary); }
a.key:hover { color: var(--el-color-primary); }
.more { display: inline-flex; align-items: center; gap: 2px; font-size: var(--fs-13); }
.group { display: flex; flex-direction: column; gap: var(--space-2); }
.group-head { display: flex; align-items: baseline; gap: var(--space-2); }
.group-label { font-size: var(--fs-13); font-weight: var(--fw-medium); color: var(--text-primary); }
.thumbs { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.detail { display: flex; flex-direction: column; gap: var(--space-2); padding-top: var(--space-3); border-top: 1px solid var(--border); }
.detail-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.view { margin: 0; text-align: center; }
.kv { display: flex; flex-direction: column; gap: var(--space-1); margin: 0; }
.kv > div { display: flex; align-items: baseline; gap: var(--space-3); }
.kv dt { flex: none; width: 56px; font-size: var(--fs-13); color: var(--text-secondary); }
.kv dd { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-2); margin: 0; }
.num { font-size: var(--fs-16); font-variant-numeric: tabular-nums; color: var(--text-primary); }
.none { margin: 0; }
.detail :deep(.el-divider) { margin: var(--space-2) 0; }
</style>
