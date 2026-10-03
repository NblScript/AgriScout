<script setup lang="ts">
/** 顶栏（计划 0018 设计 3）：面包屑（末段即页面标题）+ 地块切换器 + 展示屏入口 + 用户菜单。 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Expand, Monitor } from '@element-plus/icons-vue'
import { useUiStore, type Crumb } from '../stores/ui'
import FieldSwitcher from './FieldSwitcher.vue'
import UserMenu from './UserMenu.vue'
import { matchNav, navGroupOf } from './nav'

defineProps<{ mobile: boolean }>()

const route = useRoute()
const ui = useUiStore()

/** 页面没自报面包屑时：一级页显示「分组 / 页面」，下级页显示「所属导航项 / 页面」 */
const crumbs = computed<Crumb[]>(() => {
  if (ui.trail.length) return ui.trail
  const title = route.meta.title ?? ''
  const nav = matchNav(route.path)
  if (!nav) return [{ label: title }]
  if (nav.path !== route.path && nav.label !== title) return [{ label: nav.label, to: nav.path }, { label: title }]
  const group = navGroupOf(nav)
  return group ? [{ label: group.label }, { label: title || nav.label }] : [{ label: title || nav.label }]
})
</script>

<template>
  <header class="topbar">
    <button v-if="mobile" class="menu-btn" type="button" aria-label="打开导航" @click="ui.mobileNavOpen = true">
      <el-icon :size="20"><Expand /></el-icon>
    </button>

    <nav class="crumbs" aria-label="面包屑">
      <template v-for="(crumb, index) in crumbs" :key="`${index}-${crumb.label}`">
        <span v-if="index > 0" class="sep" aria-hidden="true">/</span>
        <router-link v-if="crumb.to && index < crumbs.length - 1" :to="crumb.to" class="crumb link">
          {{ crumb.label }}
        </router-link>
        <span v-else class="crumb" :class="{ current: index === crumbs.length - 1 }"
              :aria-current="index === crumbs.length - 1 ? 'page' : undefined">{{ crumb.label }}</span>
      </template>
    </nav>

    <div class="actions">
      <FieldSwitcher v-if="!mobile" />
      <router-link to="/screen" class="screen-link" title="全屏展示各大棚状态（答辩投影用）">
        <el-icon :size="16"><Monitor /></el-icon>
        <span v-if="!mobile">展示屏</span>
      </router-link>
      <span class="divider" aria-hidden="true" />
      <UserMenu :compact="mobile" />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: var(--topbar-height);
  padding: 0 var(--space-5);
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--border);
  backdrop-filter: saturate(1.2) blur(6px);
}
.menu-btn {
  display: inline-flex;
  margin-left: calc(-1 * var(--space-2));
  padding: var(--space-2);
  border: none;
  background: none;
  color: var(--text-regular);
  cursor: pointer;
}
.crumbs {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  overflow: hidden;
  white-space: nowrap;
  font-size: var(--fs-14);
}
.crumb { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; }
.crumb.link { color: var(--text-secondary); text-decoration: none; }
.crumb.link:hover { color: var(--brand-700); text-decoration: underline; text-underline-offset: 3px; }
.crumb.current { color: var(--text-primary); font-weight: var(--fw-semibold); }
.sep { color: var(--text-placeholder); flex: none; }
.actions { display: flex; align-items: center; gap: var(--space-3); flex: none; }
.screen-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-regular);
  font-size: var(--fs-13);
  text-decoration: none;
}
.screen-link:hover { color: var(--brand-700); border-color: var(--brand-300); background: var(--brand-50); }
.divider { width: 1px; height: 24px; background: var(--border); }
@media (max-width: 767px) {
  .topbar { padding: 0 var(--space-4); }
  /* 手机上只留末段（页面标题） */
  .crumb:not(.current), .sep { display: none; }
  .screen-link { padding: 0 var(--space-2); }
  .divider { display: none; }
}
</style>
