<script setup lang="ts">
/** 管理台外壳（计划 0018 设计 3）：固定侧栏 + 吸顶顶栏 + 内容区；768px 以下侧栏变抽屉。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUiStore } from '../stores/ui'
import AppSidebar from './AppSidebar.vue'
import AppTopbar from './AppTopbar.vue'

const ui = useUiStore()
const route = useRoute()

const query = window.matchMedia('(max-width: 767px)')
const mobile = ref(query.matches)
function onMedia(event: MediaQueryListEvent) {
  mobile.value = event.matches
  if (!event.matches) ui.mobileNavOpen = false
}
onMounted(() => query.addEventListener('change', onMedia))
onBeforeUnmount(() => query.removeEventListener('change', onMedia))

/**
 * 页面重建的键：一般按路径（各页在 setup 里只读一次路由参数，顶栏切换地块只换参数）；
 * 有子路由的页（大棚详情的标签页）按父路由 + 参数，切标签只换子页，页头和已拉的数据留着。
 */
const viewKey = computed(() => {
  const parent = route.matched.length > 1 ? route.matched[0] : null
  return parent ? `${parent.path}?${JSON.stringify(route.params)}` : route.path
})

// 换页：手机抽屉收起；待确认角标顺带刷新（15 秒内不重复请求）
watch(() => route.fullPath, () => {
  ui.mobileNavOpen = false
  void ui.refreshConfirmCount()
}, { immediate: true })
</script>

<template>
  <div class="shell" :class="{ collapsed: ui.sidebarCollapsed && !mobile, mobile }">
    <AppSidebar :mobile="mobile" />
    <div v-if="mobile && ui.mobileNavOpen" class="mask" @click="ui.mobileNavOpen = false" />
    <div class="shell-main">
      <AppTopbar :mobile="mobile" />
      <main class="content">
        <div class="content-inner"><router-view :key="viewKey" /></div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell { min-height: 100vh; }
.shell-main {
  min-width: 0;
  min-height: 100vh;
  margin-left: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  transition: margin-left 0.18s ease;
}
.collapsed .shell-main { margin-left: var(--sidebar-width-collapsed); }
.mobile .shell-main { margin-left: 0; }
.content { flex: 1; min-width: 0; padding: var(--space-5) var(--space-5) var(--space-6); }
.content-inner { max-width: var(--content-max-width); margin: 0 auto; }
.mask { position: fixed; inset: 0; z-index: 25; background: var(--el-overlay-color-lighter); }
@media (max-width: 767px) {
  .content { padding: var(--space-4) var(--space-4) var(--space-5); }
}
</style>
