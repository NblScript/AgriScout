<script setup lang="ts">
/** 巡检回放 · 大田模式：地块地图上的轨迹和采样点，按采样点播放，右侧采样点卡。功能与改版前一致。 */
import { computed, ref } from 'vue'
import MapCanvas from '../MapCanvas.vue'
import SectionCard from '../ui/SectionCard.vue'
import PatrolPlayer from './PatrolPlayer.vue'
import PatrolPointCard from './PatrolPointCard.vue'
import { NO_ANALYSIS_COLOR, VIGOR_COLORS, type CapturePointFull, type PatrolDetail } from '../../types'

const props = defineProps<{
  patrol: PatrolDetail
  points: CapturePointFull[]
  boundary: { type: string; coordinates: number[][][] } | null
}>()
const emit = defineEmits<{ annotated: [] }>()

const index = ref(0)
const player = ref<InstanceType<typeof PatrolPlayer>>()
const label = computed(() => (props.points[index.value] ? `#${props.points[index.value].seq} / ${props.points.length - 1}` : '无数据'))

function selectByPointId(pointId: number) {
  const i = props.points.findIndex((p) => p.id === pointId)
  if (i >= 0) {
    index.value = i
    player.value?.stop()
  }
}
</script>

<template>
  <div class="field-mode">
    <div class="left">
      <SectionCard flush class="map-card">
        <div class="map">
          <MapCanvas theme="light" :boundary="boundary" :track="patrol.track" :points="points" :selected-index="index"
                     @select="selectByPointId" />
          <div class="legend">
            <span v-for="(c, lv) in VIGOR_COLORS" :key="lv" class="lg"><i :style="{ background: c }" />长势{{ lv }}</span>
            <span class="lg"><i :style="{ background: NO_ANALYSIS_COLOR }" />未分析</span>
            <span class="lg"><i class="ring stress" />胁迫检出</span>
            <span class="lg"><i class="ring disease" />病害检出（模型）</span>
          </div>
        </div>
      </SectionCard>
      <SectionCard>
        <PatrolPlayer ref="player" v-model="index" :count="points.length" :label="label" />
      </SectionCard>
    </div>
    <SectionCard class="right">
      <PatrolPointCard :points="points" :index="index" @annotated="emit('annotated')" />
    </SectionCard>
  </div>
</template>

<style scoped>
.field-mode { display: grid; grid-template-columns: minmax(0, 3fr) minmax(320px, 2fr); gap: var(--space-4); align-items: start; }
.left { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.map { position: relative; height: 480px; border-radius: var(--radius-md); overflow: hidden; }
.legend {
  position: absolute;
  z-index: 500;
  left: var(--space-3);
  bottom: var(--space-3);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-3);
  max-width: calc(100% - 24px);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: var(--shadow-1);
  font-size: var(--fs-12);
  color: var(--text-regular);
}
.lg { display: inline-flex; align-items: center; gap: 4px; }
.lg i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
.lg i.ring { box-sizing: border-box; background: #fff; border: 2px solid; }
.ring.stress { border-color: #ffd54f; }
.ring.disease { border-color: #dc2626; }
.right { position: sticky; top: calc(var(--topbar-height) + var(--space-4)); max-height: calc(100vh - var(--topbar-height) - 32px); overflow: auto; }

@media (max-width: 1023px) {
  .field-mode { grid-template-columns: minmax(0, 1fr); }
  .right { position: static; max-height: none; }
  .map { height: 360px; }
}
</style>
