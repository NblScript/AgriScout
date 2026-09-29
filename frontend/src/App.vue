<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import {
  ArrowDown, Calendar, Cherry, Cpu, DataAnalysis, DataBoard, EditPen, Fold, Expand, MapLocation, Odometer, User,
  VideoCamera,
} from '@element-plus/icons-vue'
import { authApi } from './api'
import { errMsg } from './api/http'
import { useAuthStore } from './stores/auth'
import { useUiStore } from './stores/ui'
import { ROLE_LABELS } from './types'

const ui = useUiStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// 以服务端为准刷新一次当前用户（角色可能已被管理员修改；令牌失效会触发 401 回登录页）
if (auth.isAuthenticated) auth.refreshMe().catch(() => { /* 401 已由全局处理 */ })

function onCommand(command: string) {
  if (command === 'password') openPassword()
  if (command === 'logout') {
    auth.logout()
    router.replace({ name: 'login' })
  }
}

/* ---------- 修改口令 ---------- */
const pwdVisible = ref(false)
const pwdRef = ref<FormInstance>()
const pwd = reactive({ old: '', next: '', confirm: '' })
const pwdRules: FormRules = {
  old: [{ required: true, message: '请输入原口令', trigger: 'blur' }],
  next: [{ required: true, min: 8, message: '新口令至少 8 位', trigger: 'blur' }],
  confirm: [{
    validator: (_r, value, cb) => (value === pwd.next ? cb() : cb(new Error('两次输入不一致'))), trigger: 'blur',
  }],
}
const pwdSaving = ref(false)

function openPassword() {
  Object.assign(pwd, { old: '', next: '', confirm: '' })
  pwdVisible.value = true
}

async function submitPassword() {
  if (!(await pwdRef.value?.validate().catch(() => false))) return
  pwdSaving.value = true
  try {
    await authApi.changePassword(pwd.old, pwd.next)
    ElMessage.success('口令已修改')
    pwdVisible.value = false
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    pwdSaving.value = false
  }
}
</script>

<template>
  <!-- bare 路由（登录页、指挥大屏）不走管理台布局，全屏直出 -->
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
        <el-menu-item index="/research-loop">
          <el-icon><DataAnalysis /></el-icon><template #title>研究闭环</template>
        </el-menu-item>
        <el-menu-item index="/patrols">
          <el-icon><VideoCamera /></el-icon><template #title>巡检任务</template>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/users">
          <el-icon><User /></el-icon><template #title>用户管理</template>
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
        <span class="milestone">巡知 · 农田巡检与复巡决策平台</span>
        <el-dropdown v-if="auth.user" trigger="click" @command="onCommand">
          <button class="user-chip" type="button">
            <span class="avatar">{{ auth.user.display_name.slice(0, 1) }}</span>
            <span class="user-name">{{ auth.user.display_name }}</span>
            <el-tag size="small" effect="plain" :type="auth.isViewer ? 'info' : auth.isAdmin ? 'danger' : 'primary'">
              {{ ROLE_LABELS[auth.user.role] }}
            </el-tag>
            <el-icon><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>{{ auth.user.username }}</el-dropdown-item>
              <el-dropdown-item command="password" divided>修改口令</el-dropdown-item>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main"><router-view /></el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="pwdVisible" title="修改口令" width="400px">
    <el-form ref="pwdRef" :model="pwd" :rules="pwdRules" label-width="72px">
      <el-form-item label="原口令" prop="old"><el-input v-model="pwd.old" type="password" show-password autocomplete="current-password" /></el-form-item>
      <el-form-item label="新口令" prop="next"><el-input v-model="pwd.next" type="password" show-password autocomplete="new-password" /></el-form-item>
      <el-form-item label="确认" prop="confirm"><el-input v-model="pwd.confirm" type="password" show-password autocomplete="new-password" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="pwdVisible = false">取消</el-button>
      <el-button type="primary" :loading="pwdSaving" @click="submitPassword">保存</el-button>
    </template>
  </el-dialog>
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
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: none;
  color: #1f2d1f;
  font-size: 13px;
  cursor: pointer;
}
.user-chip:hover { border-color: #e4e9e4; background: #f8faf8; }
.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--el-color-primary-light-9, #e8f2ec);
  color: var(--el-color-primary, #15803d);
  font-weight: 600;
}
.user-name { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.main {
  padding: 20px;
}
</style>
