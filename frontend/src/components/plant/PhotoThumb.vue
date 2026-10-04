<script setup lang="ts">
/**
 * 单株照片缩略图（单株时间线、待确认共用）：拍摄时刻与俯仰角，第几次补拍和质量徽标并排；
 * 不合格灰显（徽标写原因，灰度下也分得清），人工确认会挂上的那张加「确认挂这张」角标。
 * selectable：巡检回放单株卡用，点图是选中这张（发 select）而不是放大，选中的加深色框。
 */
import { computed } from 'vue'
import { Picture } from '@element-plus/icons-vue'
import QualityBadge from '../ui/QualityBadge.vue'
import type { TimelinePhoto } from '../../types'
import { fieldHm } from '../../utils/fieldTime'
import { timelineAccepted, timelineQuality } from '../../utils/plantPhotos'

const props = withDefaults(defineProps<{ photo: TimelinePhoto; target?: boolean; selectable?: boolean; selected?: boolean }>(), {
  target: false,
  selectable: false,
  selected: false,
})
const emit = defineEmits<{ select: [] }>()

const quality = computed(() => timelineQuality(props.photo))
const accepted = computed(() => timelineAccepted(props.photo))
const attempt = computed(() => props.photo.view?.attempt ?? 1)
</script>

<template>
  <figure class="thumb" :class="{ bad: accepted === false, target, selectable, selected }">
    <div v-if="selectable" class="frame" role="button" tabindex="0" :aria-pressed="selected" :aria-label="`选中 ${fieldHm(photo.captured_at)} 这张`"
         @click="emit('select')" @keydown.enter.prevent="emit('select')" @keydown.space.prevent="emit('select')">
      <img v-if="photo.photo_url" :src="photo.photo_url" alt="" loading="lazy">
      <div v-else class="no-photo"><el-icon><Picture /></el-icon>无照片</div>
    </div>
    <div v-else class="frame">
      <el-image v-if="photo.photo_url" :src="photo.photo_url" :preview-src-list="[photo.photo_url]"
                fit="cover" preview-teleported lazy />
      <div v-else class="no-photo"><el-icon><Picture /></el-icon>无照片</div>
      <span v-if="target" class="target-mark">确认挂这张</span>
    </div>
    <figcaption>
      <span class="time">
        {{ fieldHm(photo.captured_at) }}<template v-if="photo.view?.pitch_deg != null"> · 俯仰 {{ photo.view.pitch_deg }}°</template>
      </span>
      <span class="badges">
        <span v-if="attempt > 1" class="attempt">第 {{ attempt }} 次</span>
        <QualityBadge :quality="quality" :accepted="accepted" />
      </span>
    </figcaption>
  </figure>
</template>

<style scoped>
.thumb { width: 148px; margin: 0; }
.frame { position: relative; width: 148px; height: 111px; border-radius: var(--radius-sm); overflow: hidden; background: var(--bg-subtle); }
.frame :deep(.el-image) { display: block; width: 100%; height: 100%; }
.frame img { display: block; width: 100%; height: 100%; object-fit: cover; }
.thumb.bad .frame :deep(.el-image), .thumb.bad .frame img { filter: grayscale(1); opacity: 0.55; }
.selectable .frame { cursor: pointer; }
.selectable .frame:focus-visible { outline: 2px solid var(--brand-600); outline-offset: 2px; }
.thumb.selected .frame { box-shadow: 0 0 0 2px var(--bg-card), 0 0 0 4px var(--neutral-900); overflow: visible; }
.thumb.selected .frame img { border-radius: var(--radius-sm); }
.thumb.target .frame::after {
  content: '';
  position: absolute;
  inset: 0;
  border: 2px solid var(--brand-600);
  border-radius: var(--radius-sm);
  pointer-events: none;
}
.no-photo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  height: 100%;
  font-size: var(--fs-12);
  color: var(--text-placeholder);
}
.target-mark {
  position: absolute;
  left: 0;
  bottom: 0;
  padding: 1px 6px;
  border-top-right-radius: var(--radius-sm);
  background: var(--brand-600);
  color: #fff;
  font-size: var(--fs-12);
  line-height: var(--lh-12);
}
figcaption { display: flex; flex-direction: column; gap: 2px; margin-top: var(--space-1); }
.time { font-size: var(--fs-12); line-height: var(--lh-12); color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.badges { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); }
.attempt {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 6px;
  border: 1px dashed var(--task-reshoot);
  border-radius: var(--radius-sm);
  color: var(--task-reshoot-ink);
  font-size: var(--fs-12);
  white-space: nowrap;
}
</style>
