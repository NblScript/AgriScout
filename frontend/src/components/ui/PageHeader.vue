<script setup lang="ts">
/** 页面抬头：标题 + 说明 + 右侧操作；meta 插槽放标题下的标签行，默认插槽放标题下方的附加内容（如标签页）。 */
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="page-header">
    <div class="ph-main">
      <div class="ph-text">
        <h1 class="ph-title">{{ title }}</h1>
        <p v-if="subtitle" class="ph-subtitle">{{ subtitle }}</p>
        <div v-if="$slots.meta" class="ph-meta"><slot name="meta" /></div>
      </div>
      <div v-if="$slots.actions" class="ph-actions"><slot name="actions" /></div>
    </div>
    <slot />
  </header>
</template>

<style scoped>
.page-header { margin-bottom: var(--space-5); }
.ph-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.ph-text { min-width: 0; }
.ph-title {
  margin: 0;
  font-size: var(--fs-24);
  line-height: var(--lh-24);
  font-weight: var(--fw-semibold);
  color: var(--text-primary);
}
.ph-subtitle {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-14);
  line-height: var(--lh-14);
  color: var(--text-secondary);
}
.ph-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.ph-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}
/* Element 按钮自带左外边距，按钮组里统一用 gap */
.ph-actions :deep(.el-button + .el-button) { margin-left: 0; }
@media (max-width: 767px) {
  .ph-title { font-size: var(--fs-20); line-height: var(--lh-20); }
}
</style>
