<script setup lang="ts">
/** 株状态标签：颜色只取令牌 --state-*；另带形状（● 健康 ▲ 早期 ■ 明显 ○ 不明），不只靠颜色区分（计划 0018）。 */
import { computed } from 'vue'
import { PLANT_STATE_LABELS, type PlantStateValue } from '../../types'

const props = withDefaults(defineProps<{ state: PlantStateValue; label?: string; size?: 'small' | 'default' }>(), {
  label: undefined,
  size: 'default',
})
const text = computed(() => props.label ?? PLANT_STATE_LABELS[props.state])
</script>

<template>
  <span class="state-tag" :class="[`is-${state}`, `size-${size}`]">
    <i class="shape" aria-hidden="true" />
    {{ text }}
  </span>
</template>

<style scoped>
.state-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-soft);
  color: var(--c-ink);
  font-size: var(--fs-12);
  font-weight: var(--fw-medium);
  line-height: 1;
  white-space: nowrap;
}
.state-tag.size-small { height: 20px; padding: 0 6px; gap: 4px; }
.is-healthy { --c-base: var(--state-healthy); --c-ink: var(--state-healthy-ink); --c-soft: var(--state-healthy-soft); }
.is-early { --c-base: var(--state-early); --c-ink: var(--state-early-ink); --c-soft: var(--state-early-soft); }
.is-symptomatic { --c-base: var(--state-symptomatic); --c-ink: var(--state-symptomatic-ink); --c-soft: var(--state-symptomatic-soft); }
.is-unknown { --c-base: var(--state-unknown); --c-ink: var(--state-unknown-ink); --c-soft: var(--state-unknown-soft); }
.shape { display: inline-block; flex: none; width: 8px; height: 8px; background: var(--c-base); }
.is-healthy .shape { border-radius: 50%; }
.is-early .shape {
  width: 0;
  height: 0;
  background: none;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-bottom: 9px solid var(--c-base);
}
.is-symptomatic .shape { border-radius: 1px; }
.is-unknown .shape { background: none; border: 1.5px solid var(--c-ink); border-radius: 50%; }
</style>
