<script setup lang="ts">
/**
 * 单株照片按田间日期分组（新的在上），每天正面、叶背两栏；栏头写张数、补拍次数、合格几张，
 * 日期行写当天最高风险分、风险预测与随访、人工结论。手机宽度两栏上下叠。
 */
import { computed } from 'vue'
import PhotoThumb from './PhotoThumb.vue'
import EmptyState from '../ui/EmptyState.vue'
import {
  ANNOTATION_LABELS, FOLLOW_UP_LABELS, RISK_LEVEL_LABELS, RISK_LEVEL_TAG_TYPES,
  type AnnotationLabel, type TimelineDay, type TimelinePhoto,
} from '../../types'
import { fieldDayLabel } from '../../utils/fieldTime'
import { photoSide, timelineAccepted, type PhotoSide } from '../../utils/plantPhotos'

const props = withDefaults(defineProps<{ days: TimelineDay[]; targetId?: number | null; emptyText?: string }>(), {
  targetId: null,
  emptyText: '这株在回看期内还没有照片',
})

const SIDES: { side: PhotoSide; label: string }[] = [
  { side: 'upper', label: '正面' },
  { side: 'under', label: '叶背' },
]

interface Column { side: PhotoSide; label: string; photos: TimelinePhoto[]; reshoots: number; ok: number }
interface DayRow {
  day: TimelineDay
  columns: Column[]
  maxRisk: number | null
  prediction: TimelineDay['predictions'][number] | null
}

const rows = computed<DayRow[]>(() => props.days.slice().reverse().map((day) => {
  const columns = SIDES.map(({ side, label }) => {
    const photos = day.photos
      .filter((p) => photoSide(p.view) === side)
      .sort((a, b) => Date.parse(a.captured_at) - Date.parse(b.captured_at))
    return {
      side, label, photos,
      reshoots: photos.filter((p) => (p.view?.attempt ?? 1) > 1).length,
      ok: photos.filter((p) => timelineAccepted(p) === true).length,
    }
  })
  const risks = day.photos.map((p) => p.analysis?.risk_score).filter((v): v is number => v != null)
  const prediction = day.predictions.reduce<DayRow['prediction']>(
    (best, p) => (best == null || p.probability > best.probability ? p : best), null)
  return { day, columns, maxRisk: risks.length ? Math.max(...risks) : null, prediction }
}))

function columnSummary(col: Column): string {
  if (!col.photos.length) return '没拍'
  const parts = [`${col.photos.length} 张`]
  if (col.reshoots) parts.push(`补拍 ${col.reshoots} 次`)
  parts.push(`合格 ${col.ok}`)
  return parts.join(' · ')
}
function annotationText(label: string): string {
  return ANNOTATION_LABELS[label as AnnotationLabel] ?? label
}
</script>

<template>
  <div v-if="rows.length" class="days">
    <section v-for="row in rows" :key="row.day.field_date" class="day">
      <header class="day-head">
        <span class="date">{{ fieldDayLabel(row.day.field_date) }}</span>
        <span v-if="row.maxRisk != null" class="fact">风险分 <b>{{ row.maxRisk.toFixed(2) }}</b></span>
        <span v-if="row.prediction" class="fact">
          <el-tag :type="RISK_LEVEL_TAG_TYPES[row.prediction.level] ?? 'info'" size="small" effect="plain">
            预测{{ RISK_LEVEL_LABELS[row.prediction.level] ?? row.prediction.level }} {{ (row.prediction.probability * 100).toFixed(0) }}%
          </el-tag>
          {{ row.prediction.follow_up_status ? FOLLOW_UP_LABELS[row.prediction.follow_up_status] ?? row.prediction.follow_up_status : '未随访' }}
        </span>
        <span v-for="a in row.day.annotations" :key="a.id" class="fact human">
          人工：<b>{{ annotationText(a.label) }}</b> · {{ a.annotator_name }}
        </span>
      </header>
      <div class="cols">
        <div v-for="col in row.columns" :key="col.side" class="col">
          <div class="col-head">
            <span class="col-label">{{ col.label }}</span>
            <span class="muted text-12">{{ columnSummary(col) }}</span>
          </div>
          <div v-if="col.photos.length" class="thumbs">
            <PhotoThumb v-for="photo in col.photos" :key="photo.capture_point_id" :photo="photo"
                        :target="photo.capture_point_id === targetId" />
          </div>
        </div>
      </div>
    </section>
  </div>
  <EmptyState v-else compact :title="emptyText" description="小车巡到这株、上传巡检包后按天出现在这里" />
</template>

<style scoped>
.days { display: flex; flex-direction: column; }
.day { padding: var(--space-4) 0; }
.day:first-child { padding-top: 0; }
.day + .day { border-top: 1px solid var(--border); }
.day-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-4); margin-bottom: var(--space-3); }
.date { font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text-primary); font-variant-numeric: tabular-nums; }
.fact { display: inline-flex; align-items: center; gap: var(--space-1); font-size: var(--fs-13); color: var(--text-secondary); }
.fact b { color: var(--text-primary); font-weight: var(--fw-medium); font-variant-numeric: tabular-nums; }
.fact.human b { color: var(--brand-700); }
.cols { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: var(--space-4); }
.col { min-width: 0; padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-subtle); }
.col-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-2); }
.col-head + .thumbs { margin-top: var(--space-2); }
.col-label { font-size: var(--fs-13); font-weight: var(--fw-medium); color: var(--text-primary); }
.thumbs { display: flex; flex-wrap: wrap; gap: var(--space-3); }

@media (max-width: 767px) {
  .cols { grid-template-columns: minmax(0, 1fr); gap: var(--space-3); }
}
</style>
