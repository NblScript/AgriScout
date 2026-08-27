<script setup lang="ts">
/** 大屏科技风面板：四角切口边框 + 标题栏 + 底部扫光（参考 sc-datav 构图，农业绿配色）。 */
withDefaults(defineProps<{
  title: string
  subtitle?: string
  height?: string
}>(), { height: 'auto' })
</script>

<template>
  <section class="screen-panel" :style="{ height }">
    <header class="sp-head">
      <i class="sp-accent" />
      <h3>{{ title }}</h3>
      <span v-if="subtitle" class="sp-sub">{{ subtitle }}</span>
    </header>
    <div class="sp-body">
      <slot />
    </div>
    <i class="corner tl" /><i class="corner tr" /><i class="corner bl" /><i class="corner br" />
    <i class="sweep" />
  </section>
</template>

<style scoped>
.screen-panel {
  position: relative;
  background: linear-gradient(160deg, rgba(16, 38, 24, 0.88), rgba(10, 24, 15, 0.92));
  border: 1px solid rgba(74, 222, 128, 0.22);
  border-radius: 8px;
  padding: 10px 14px 12px;
  overflow: hidden;
  backdrop-filter: blur(2px);
}
.sp-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(74, 222, 128, 0.16);
}
.sp-accent {
  width: 4px;
  height: 14px;
  border-radius: 2px;
  background: linear-gradient(#4ade80, #166534);
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.8);
}
.sp-head h3 {
  font-size: 14px;
  letter-spacing: 1px;
  color: #d1fae5;
}
.sp-sub {
  margin-left: auto;
  font-size: 10px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: rgba(116, 173, 132, 0.75);
}
.sp-body {
  position: relative;
  height: calc(100% - 34px);
}
.corner {
  position: absolute;
  width: 10px;
  height: 10px;
  border-color: #4ade80;
  border-style: solid;
  opacity: 0.9;
}
.tl { top: -1px; left: -1px; border-width: 2px 0 0 2px; border-radius: 8px 0 0 0; }
.tr { top: -1px; right: -1px; border-width: 2px 2px 0 0; border-radius: 0 8px 0 0; }
.bl { bottom: -1px; left: -1px; border-width: 0 0 2px 2px; border-radius: 0 0 0 8px; }
.br { bottom: -1px; right: -1px; border-width: 0 2px 2px 0; border-radius: 0 0 8px 0; }
/* 顶部缓慢扫过的光带，纯 CSS，无运行时开销 */
.sweep {
  position: absolute;
  top: 0;
  left: -30%;
  width: 30%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(74, 222, 128, 0.9), transparent);
  animation: sp-sweep 7s linear infinite;
  pointer-events: none;
}
@keyframes sp-sweep {
  to { left: 100%; }
}
</style>
