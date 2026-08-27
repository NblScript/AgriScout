<script setup lang="ts">
/** 总览面板：白底卡片 + 左侧品牌色标题条。信息层级靠字重与留白，不靠装饰。 */
withDefaults(defineProps<{
  title: string
  subtitle?: string
  height?: string
}>(), { height: 'auto' })
</script>

<template>
  <section class="ov-panel" :style="{ height }">
    <header class="ov-head">
      <i class="ov-accent" />
      <h3>{{ title }}</h3>
      <span v-if="subtitle" class="ov-sub">{{ subtitle }}</span>
    </header>
    <div class="ov-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.ov-panel {
  position: relative;
  background: #fff;
  border: 1px solid #e2e8e2;
  border-radius: 10px;
  padding: 12px 14px;
  overflow: hidden;
}
.ov-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  margin-bottom: 8px;
  border-bottom: 1px solid #eef2ee;
}
.ov-accent {
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: var(--el-color-primary, #15803d);
}
.ov-head h3 {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d1f;
}
.ov-sub {
  margin-left: auto;
  font-size: 11px;
  color: #8a978a;
}
.ov-body {
  position: relative;
  height: calc(100% - 36px);
}
</style>
