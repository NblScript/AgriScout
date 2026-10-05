<script setup lang="ts">
/** 一个采样点的检出列表：名称按类型映射，病害模型检出标红并写置信度、病斑图块占比；悬停看分析器给的原文。 */
import { WarningFilled } from '@element-plus/icons-vue'
import { detectionLabel, isDiseaseModelDetection, type DiseaseDetection } from '../../types'

defineProps<{ detections: DiseaseDetection[] }>()

function detail(d: DiseaseDetection): string {
  const parts: string[] = []
  if (isDiseaseModelDetection(d) && typeof d.confidence === 'number') parts.push(`置信度 ${Math.round(d.confidence * 100)}%`)
  if (typeof d.area_ratio === 'number') parts.push(`病斑图块 ${Math.round(d.area_ratio * 100)}%`)
  return parts.join(' · ')
}
</script>

<template>
  <div v-if="detections.length" class="detections">
    <el-tooltip v-for="(d, i) in detections" :key="i" :content="d.label ?? d.type ?? '检出'" placement="top" :show-after="200">
      <el-tag :type="isDiseaseModelDetection(d) ? 'danger' : 'warning'" effect="plain">
        <el-icon class="icon"><WarningFilled /></el-icon>
        {{ isDiseaseModelDetection(d) ? '模型检出' : '' }}{{ detectionLabel(d) }}<template v-if="detail(d)"> · {{ detail(d) }}</template>
      </el-tag>
    </el-tooltip>
  </div>
</template>

<style scoped>
.detections { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.icon { margin-right: 2px; vertical-align: -2px; }
</style>
