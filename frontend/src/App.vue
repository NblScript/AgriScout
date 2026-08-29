<script setup lang="ts">
import { useRoute } from 'vue-router'
import { Calendar, Cherry, Cpu, DataBoard, EditPen, Fold, Expand, MapLocation, Odometer, VideoCamera } from '@element-plus/icons-vue'
import { useUiStore } from './stores/ui'

const ui = useUiStore()
const route = useRoute()
</script>

<template>
  <!-- bare 路由（指挥大屏）不走管理台布局，全屏直出 -->
  <router-view v-if="route.meta.bare" />

  <el-container v-else class="layout">
    <el-aside :width="ui.sidebarCollapsed ? '64px' : '200px'" class="aside">
      <div class="brand" title="AgriScout 农田巡检平台">
        <span v-if="ui.sidebarCollapsed" class="brand-mark">Ag</span>
        <template v-else><i class="brand-dot" /> AgriScout</template>
      </div>
      <el-menu
        router
        :default-active="route.path"
        :collapse="ui.sidebarCollapsed"
        class="menu"
        collapse-transition
      >
        <el-menu-item index="/screen">
          <el-icon><DataBoard /></el-icon><template #title>数据总览</template>
        </el-menu-item>
        <el-menu-item index="/dashboard">
          <el-icon><Odometer /></el-icon><template #title>系统状态</template>
        </el-menu-item>
        <el-menu-item index="/fields">
          <el-icon><MapLocation /></el-icon><template #title>地块管理</template>
        </el-menu-item>
        <el-menu-item index="/crops">
          <el-icon><Cherry /></el-icon><template #title>作物管理</template>
        </el-menu-item>
        <el-menu-item index="/plantings">
          <el-icon><Calendar /></el-icon><template #title>种植记录</template>
        </el-menu-item>
        <el-menu-item index="/devices">
          <el-icon><Cpu /></el-icon><template #title>设备管理</template>
        </el-menu-item>
        <el-menu-item index="/rule-revisions">
          <el-icon><EditPen /></el-icon><template #title>规则修订审批</template>
        </el-menu-item>
        <el-menu-item index="/patrols">
          <el-icon><VideoCamera /></el-icon><template #title>巡检任务</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <el-button text @click="ui.toggleSidebar" aria-label="折叠侧栏">
          <el-icon v-if="ui.sidebarCollapsed"><Expand /></el-icon>
          <el-icon v-else><Fold /></el-icon>
        </el-button>
        <h2 class="page-title">{{ route.meta.title }}</h2>
        <span class="milestone">M1 · 基础管理</span>
      </el-header>
      <el-main class="main"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.aside {
  background: #fff;
  border-right: 1px solid #e4e9e4;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 18px;
  font-weight: 600;
  color: #1f2d1f;
}
.brand-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  background: var(--el-color-primary, #15803d);
}
.brand-mark {
  font-size: 15px;
  font-weight: 700;
  color: var(--el-color-primary, #15803d);
}
.menu {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #fff;
  border-bottom: 1px solid #e4e9e4;
}
.page-title {
  font-size: 17px;
  color: #1f2d1f;
}
.milestone {
  margin-left: auto;
  font-size: 12px;
  color: #8a978a;
}
.main {
  padding: 20px;
}
</style>
