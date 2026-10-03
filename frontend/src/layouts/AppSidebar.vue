<script setup lang="ts">
/** 分组侧栏（计划 0018 设计 3）：桌面可折叠成图标栏（悬停出名称），手机宽度下是抽屉。 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Close, DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { NAV_GROUPS, matchNav, type NavItem } from './nav'

const props = defineProps<{ mobile: boolean }>()

const route = useRoute()
const auth = useAuthStore()
const ui = useUiStore()

const collapsed = computed(() => ui.sidebarCollapsed && !props.mobile)
const groups = computed(() => NAV_GROUPS
  .map((group) => ({ ...group, items: group.items.filter((item) => !item.adminOnly || auth.isAdmin) }))
  .filter((group) => group.items.length))
const active = computed(() => matchNav(route.path))

function badge(item: NavItem): string {
  if (item.badge !== 'confirm' || !ui.confirmCount) return ''
  if (ui.confirmCount > 99) return '99+'
  return ui.confirmCapped ? `${ui.confirmCount}+` : String(ui.confirmCount)
}
function tooltip(item: NavItem): string {
  const count = badge(item)
  return count ? `${item.label}（${count}）` : item.label
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed, mobile, open: mobile && ui.mobileNavOpen }" aria-label="主导航">
    <div class="brand">
      <span class="logo" aria-hidden="true">巡</span>
      <span v-if="!collapsed" class="brand-text">
        <b>巡知</b>
        <small>设施大棚病害主动巡检</small>
      </span>
      <button v-if="mobile" class="close" type="button" aria-label="关闭导航" @click="ui.mobileNavOpen = false">
        <el-icon :size="18"><Close /></el-icon>
      </button>
    </div>

    <nav class="nav">
      <div v-for="(group, index) in groups" :key="group.label" class="group">
        <div v-if="!collapsed" class="group-label">{{ group.label }}</div>
        <div v-else-if="index > 0" class="group-divider" />
        <el-tooltip
          v-for="item in group.items"
          :key="item.path"
          :content="tooltip(item)"
          placement="right"
          :disabled="!collapsed"
          :show-after="120"
        >
          <router-link
            :to="item.path"
            class="nav-item"
            :class="{ active: active === item }"
            :aria-current="active === item ? 'page' : undefined"
            :aria-label="collapsed ? tooltip(item) : undefined"
          >
            <el-icon class="nav-icon" :size="18"><component :is="item.icon" /></el-icon>
            <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
            <span v-if="badge(item)" class="nav-badge">{{ badge(item) }}</span>
          </router-link>
        </el-tooltip>
      </div>
    </nav>

    <button v-if="!mobile" class="collapse-btn" type="button" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
            @click="ui.toggleSidebar">
      <el-icon :size="14"><DArrowRight v-if="collapsed" /><DArrowLeft v-else /></el-icon>
      <span v-if="!collapsed">收起侧栏</span>
    </button>
  </aside>
</template>

<style scoped>
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  background: var(--bg-card);
  border-right: 1px solid var(--border);
  transition: width 0.18s ease, transform 0.2s ease;
}
.sidebar.collapsed { width: var(--sidebar-width-collapsed); }
.sidebar.mobile { width: 248px; transform: translateX(-100%); box-shadow: none; }
.sidebar.mobile.open { transform: none; box-shadow: var(--shadow-2); }

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: var(--topbar-height);
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--border);
  flex: none;
}
.collapsed .brand { justify-content: center; padding: 0; }
.logo {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-600);
  color: #fff;
  font-size: var(--fs-16);
  font-weight: var(--fw-semibold);
}
.brand-text { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
.brand-text b { font-size: var(--fs-16); font-weight: var(--fw-semibold); color: var(--text-primary); }
.brand-text small {
  font-size: var(--fs-12);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.close {
  margin-left: auto;
  display: inline-flex;
  padding: var(--space-1);
  border: none;
  background: none;
  color: var(--text-secondary);
  cursor: pointer;
}

.nav { flex: 1; overflow-y: auto; padding: var(--space-2) var(--space-3) var(--space-4); }
.collapsed .nav { padding: var(--space-2) var(--space-2) var(--space-4); }
.group + .group { margin-top: var(--space-2); }
.group-label {
  padding: var(--space-3) var(--space-3) var(--space-1);
  font-size: var(--fs-12);
  line-height: var(--lh-12);
  color: var(--text-secondary);
}
.group-divider { height: 1px; margin: var(--space-2) var(--space-2); background: var(--border); }

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 36px;
  margin-top: 2px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-regular);
  font-size: var(--fs-14);
  text-decoration: none;
  transition: background-color 0.12s ease, color 0.12s ease;
}
.collapsed .nav-item { justify-content: center; padding: 0; }
.nav-item:hover { background: var(--neutral-100); color: var(--text-primary); }
.nav-item:focus-visible { outline: 2px solid var(--brand-300); outline-offset: -2px; }
.nav-item.active { background: var(--brand-50); color: var(--brand-700); font-weight: var(--fw-medium); }
.nav-icon { flex: none; color: var(--text-secondary); }
.nav-item:hover .nav-icon { color: var(--text-regular); }
.nav-item.active .nav-icon { color: var(--brand-600); }
.nav-label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* 待确认角标用「确认」任务色，与计划页、标签同义 */
.nav-badge {
  flex: none;
  min-width: 20px;
  height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--task-confirm);
  color: #fff;
  font-size: var(--fs-12);
  line-height: 18px;
  font-weight: var(--fw-medium);
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.collapsed .nav-badge {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  font-size: 10px;
  line-height: 16px;
}

.collapse-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 44px;
  padding: 0 var(--space-5);
  border: none;
  border-top: 1px solid var(--border);
  background: none;
  color: var(--text-secondary);
  font: inherit;
  font-size: var(--fs-13);
  cursor: pointer;
  flex: none;
}
.collapsed .collapse-btn { justify-content: center; padding: 0; }
.collapse-btn:hover { color: var(--text-primary); background: var(--bg-subtle); }
</style>
