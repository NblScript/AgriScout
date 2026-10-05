<script setup lang="ts">
/**
 * 采样点照片 + 病害模型的病斑框（归一化 [x, y, w, h] 叠在同尺寸容器上，所以照片按原比例完整显示，不能裁剪）。
 * 框的说明按检出类型映射（types.ts DETECTION_TYPE_LABELS），不再写死某种病。
 */
import { computed, ref } from 'vue'
import { Picture } from '@element-plus/icons-vue'
import { detectionLabel, isDiseaseModelDetection, type CapturePointFull } from '../../types'

/** fill：按容器宽度放大（最宽 360px，单株卡用）；否则按原尺寸、限高显示 */
const props = withDefaults(defineProps<{ point: CapturePointFull; maxHeight?: number; gray?: boolean; fill?: boolean }>(), {
  maxHeight: 220,
  gray: false,
  fill: false,
})

const showBoxes = ref(true)
const modelDetections = computed(() => (props.point.analysis?.disease_detections ?? []).filter(isDiseaseModelDetection))
const boxes = computed<number[][]>(() => modelDetections.value.flatMap((d) => (Array.isArray(d.boxes) ? d.boxes : [])))
const boxLabel = computed(() => [...new Set(modelDetections.value.map(detectionLabel))].join('、'))
</script>

<template>
  <div class="point-photo">
    <div v-if="point.photo_url" class="wrap" :class="{ fill }">
      <el-image :src="point.photo_url" :preview-src-list="[point.photo_url]" preview-teleported hide-on-click-modal
                class="photo" :class="{ gray }" :style="{ '--max-h': `${maxHeight}px` }" alt="采样照片（点击放大）" />
      <template v-if="showBoxes">
        <span v-for="(b, i) in boxes" :key="i" class="box"
              :style="{ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${b[2] * 100}%`, height: `${b[3] * 100}%` }" />
      </template>
    </div>
    <div v-else class="none"><el-icon><Picture /></el-icon>这个点没有照片</div>
    <label v-if="boxes.length" class="toggle">
      <el-switch v-model="showBoxes" size="small" />
      <span>病斑框（模型判为{{ boxLabel }}的图块，{{ boxes.length }} 块）</span>
    </label>
  </div>
</template>

<style scoped>
.point-photo { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); }
.wrap { position: relative; display: inline-block; max-width: 100%; line-height: 0; }
.photo { display: block; border-radius: var(--radius-sm); }
.photo :deep(.el-image__inner) { display: block; max-width: 100%; max-height: var(--max-h); width: auto; height: auto; }
.wrap.fill { width: 100%; max-width: 360px; }
.wrap.fill .photo :deep(.el-image__inner) { width: 100%; max-height: none; }
.photo.gray :deep(.el-image__inner) { filter: grayscale(1); opacity: 0.6; }
.box {
  position: absolute;
  box-sizing: border-box;
  border: 2px solid var(--danger);
  border-radius: 2px;
  pointer-events: none; /* 点击穿透到照片，保留放大预览 */
}
.none {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  width: 100%;
  height: 120px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  color: var(--text-placeholder);
  font-size: var(--fs-13);
}
.toggle { display: flex; align-items: center; gap: var(--space-2); font-size: var(--fs-12); color: var(--text-secondary); line-height: var(--lh-12); cursor: pointer; }
</style>
