<script setup lang="ts">
/** 空状态：图标 + 一句话 + 说明 + 可选操作（不用 el-empty 的插画，保持克制）。 */
import type { Component } from 'vue'
import { Box } from '@element-plus/icons-vue'

withDefaults(defineProps<{ title?: string; description?: string; icon?: Component; compact?: boolean }>(), {
  title: '暂无数据',
  description: undefined,
  icon: () => Box,
  compact: false,
})
</script>

<template>
  <div class="empty-state" :class="{ compact }">
    <span class="es-icon"><el-icon :size="compact ? 18 : 22"><component :is="icon" /></el-icon></span>
    <p class="es-title">{{ title }}</p>
    <p v-if="description" class="es-desc">{{ description }}</p>
    <div v-if="$slots.default" class="es-actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-6) var(--space-4);
}
.empty-state.compact { padding: var(--space-4) var(--space-3); }
.es-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-placeholder);
  margin-bottom: var(--space-3);
}
.compact .es-icon { width: 36px; height: 36px; margin-bottom: var(--space-2); }
.es-title {
  margin: 0;
  font-size: var(--fs-14);
  line-height: var(--lh-14);
  font-weight: var(--fw-medium);
  color: var(--text-regular);
}
.es-desc {
  margin: var(--space-1) 0 0;
  max-width: 420px;
  font-size: var(--fs-13);
  line-height: var(--lh-13);
  color: var(--text-secondary);
}
.es-actions { margin-top: var(--space-4); display: flex; gap: var(--space-2); }
</style>
