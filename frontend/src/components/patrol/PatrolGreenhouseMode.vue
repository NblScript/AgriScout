<script setup lang="ts">
/**
 * 巡检回放 · 大棚模式（计划 0018 阶段 B）：左侧「垄 × 株」网格标出本次巡到的株（颜色是每株当前状态），
 * 下方按巡检顺序逐株播放；右侧单株卡看这株本次的全部照片。点网格里巡到的株直接跳过去。
 */
import { computed, onMounted, ref } from 'vue'
import PlantGrid from '../PlantGrid.vue'
import EmptyState from '../ui/EmptyState.vue'
import SectionCard from '../ui/SectionCard.vue'
import PatrolPlantCard from './PatrolPlantCard.vue'
import PatrolPlayer from './PatrolPlayer.vue'
import { greenhouseApi } from '../../api'
import type { CapturePointFull, PatrolDetail, PlantState } from '../../types'
import { groupVisits } from '../../utils/patrolVisits'
import { isAccepted, photoSide, pointQuality } from '../../utils/plantPhotos'

const props = defineProps<{ patrol: PatrolDetail; points: CapturePointFull[] }>()
const emit = defineEmits<{ annotated: [] }>()

const states = ref<PlantState[]>([])
const statesLoaded = ref(false)
onMounted(async () => {
  try {
    states.value = await greenhouseApi.plantStates(props.patrol.field_id)
  } catch { /* 没有网格也能按株回放 */ } finally {
    statesLoaded.value = true
  }
})
const stateByUnit = computed(() => new Map(states.value.map((s) => [s.unit_id, s])))

const visits = computed(() => groupVisits(props.points))
const visited = computed(() => new Set(visits.value.flatMap((v) => (v.unitId != null ? [v.unitId] : []))))
const index = ref(0)
const player = ref<InstanceType<typeof PatrolPlayer>>()
const visit = computed(() => visits.value[index.value] ?? null)
const label = computed(() => (visit.value ? `第 ${index.value + 1} / ${visits.value.length} 株` : '无数据'))

function pick(unitId: number) {
  const i = visits.value.findIndex((v) => v.unitId === unitId)
  if (i >= 0) {
    index.value = i
    player.value?.stop()
  }
}

/** 本次叶背情况：拍到叶背的株里，至少一张合格的有几株 */
const underSummary = computed(() => {
  let shot = 0
  let ok = 0
  for (const v of visits.value) {
    const under = v.points.filter((p) => photoSide(p.view) === 'under')
    if (!under.length) continue
    shot += 1
    if (under.some((p) => isAccepted(p.view, pointQuality(p)) === true)) ok += 1
  }
  return { shot, ok }
})
const loose = computed(() => visits.value.filter((v) => v.unitId == null).length)
</script>

<template>
  <div class="gh-mode">
    <div class="left">
      <SectionCard title="本次巡到的株"
                   :subtitle="`巡到 ${visited.size} 株${loose ? `，另有 ${loose} 个点没关联到株` : ''}；拍到叶背 ${underSummary.shot} 株，其中有合格叶背 ${underSummary.ok} 株。颜色是每株当前状态，点巡到的株看照片`">
        <PlantGrid v-if="statesLoaded && states.length" :states="states" :visited="visited" :selected="visit?.unitId ?? null"
                   :navigable="false" :max-cell="32" @pick="pick" />
        <el-skeleton v-else-if="!statesLoaded" animated :rows="5" />
        <EmptyState v-else compact title="这个大棚还没有株档案" description="下面仍可按采样点逐个回放" />
      </SectionCard>
      <SectionCard>
        <PatrolPlayer ref="player" v-model="index" :count="visits.length" :label="label" :interval="600" />
        <ol v-if="visits.length" class="order" aria-label="巡检顺序">
          <li v-for="(v, i) in visits" :key="v.key">
            <button type="button" class="chip" :class="{ on: i === index }" @click="index = i; player?.stop()">{{ v.label }}</button>
          </li>
        </ol>
      </SectionCard>
    </div>
    <SectionCard class="right">
      <PatrolPlantCard v-if="visit" :visit="visit" :state="visit.unitId != null ? stateByUnit.get(visit.unitId) ?? null : null"
                       @annotated="emit('annotated')" />
      <EmptyState v-else compact title="这次巡检没有采样点" />
    </SectionCard>
  </div>
</template>

<style scoped>
.gh-mode { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 440px); gap: var(--space-4); align-items: start; }
.left { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.order { display: flex; flex-wrap: wrap; gap: var(--space-1); margin: var(--space-3) 0 0; padding: 0; list-style: none; max-height: 120px; overflow: auto; }
.chip {
  height: 26px;
  padding: 0 var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  color: var(--text-regular);
  cursor: pointer;
}
.chip:hover { border-color: var(--brand-400); }
.chip.on { border-color: var(--neutral-900); background: var(--neutral-900); color: #fff; }
.chip:focus-visible { outline: 2px solid var(--brand-600); outline-offset: 1px; }
.right { position: sticky; top: calc(var(--topbar-height) + var(--space-4)); max-height: calc(100vh - var(--topbar-height) - 32px); overflow: auto; }

@media (max-width: 1023px) {
  .gh-mode { grid-template-columns: minmax(0, 1fr); }
  .right { position: static; max-height: none; }
}
</style>
