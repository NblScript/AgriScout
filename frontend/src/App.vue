<script setup lang="ts">
import { useRoute } from 'vue-router'
import AppShell from './layouts/AppShell.vue'
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
const route = useRoute()

// 以服务端为准刷新一次当前用户（角色可能已被管理员修改；令牌失效会触发 401 回登录页）
if (auth.isAuthenticated) auth.refreshMe().catch(() => { /* 401 已由全局处理 */ })
</script>

<template>
  <!-- bare 路由（登录页、展示屏）不走管理台外壳，全屏直出 -->
  <router-view v-if="route.meta.bare" />
  <AppShell v-else />
</template>
