<script setup lang="ts">
/** 内容分区卡片：白底、细描边、单层浅阴影。flush 时内容贴边（放表格），否则留内边距。 */
withDefaults(defineProps<{ title?: string; subtitle?: string; flush?: boolean }>(), {
  title: undefined,
  subtitle: undefined,
  flush: false,
})
</script>

<template>
  <section class="section-card">
    <header v-if="title || $slots.title || $slots.actions" class="sc-header">
      <div class="sc-heading">
        <slot name="title"><h2 class="sc-title">{{ title }}</h2></slot>
        <p v-if="subtitle" class="sc-subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="sc-actions"><slot name="actions" /></div>
    </header>
    <div class="sc-body" :class="{ flush }"><slot /></div>
    <footer v-if="$slots.footer" class="sc-footer"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.section-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
  min-width: 0;
  overflow: hidden; /* 贴边表格的表头底色不溢出圆角 */
}
.sc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
}
.sc-heading { min-width: 0; }
.sc-title {
  margin: 0;
  font-size: var(--fs-16);
  line-height: var(--lh-16);
  font-weight: var(--fw-semibold);
  color: var(--text-primary);
}
.sc-subtitle {
  margin: 2px 0 0;
  font-size: var(--fs-13);
  line-height: var(--lh-13);
  color: var(--text-secondary);
}
.sc-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.sc-actions :deep(.el-button + .el-button) { margin-left: 0; }
.sc-body { padding: var(--space-5); }
.sc-body.flush { padding: 0; }
/* 贴边表格：去掉表格自身外框，与卡片圆角对齐 */
.sc-body.flush :deep(.el-table) { border-radius: 0 0 var(--radius-lg) var(--radius-lg); }
.sc-body.flush :deep(.el-table__inner-wrapper::before) { display: none; }
.sc-footer {
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--border);
  font-size: var(--fs-13);
  color: var(--text-secondary);
}
@media (max-width: 767px) {
  .sc-header { padding: var(--space-3) var(--space-4); }
  .sc-body { padding: var(--space-4); }
}
</style>
