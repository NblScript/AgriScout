<script setup lang="ts">
/** 顶栏用户菜单：显示姓名与角色，修改口令、退出登录（决策 D15）。 */
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { authApi } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { ROLE_LABELS } from '../types'

defineProps<{ compact?: boolean }>()

const auth = useAuthStore()
const router = useRouter()

function onCommand(command: string) {
  if (command === 'password') openPassword()
  if (command === 'logout') {
    auth.logout()
    void router.replace({ name: 'login' })
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
  <el-dropdown v-if="auth.user" trigger="click" @command="onCommand">
    <button class="user-chip" type="button" :aria-label="`当前用户 ${auth.user.display_name}`">
      <span class="avatar">{{ auth.user.display_name.slice(0, 1) }}</span>
      <template v-if="!compact">
        <span class="user-text">
          <span class="user-name">{{ auth.user.display_name }}</span>
          <span class="user-role">{{ ROLE_LABELS[auth.user.role] }}</span>
        </span>
        <el-icon class="caret"><ArrowDown /></el-icon>
      </template>
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item disabled>
          {{ auth.user.username }} · {{ ROLE_LABELS[auth.user.role] }}
        </el-dropdown-item>
        <el-dropdown-item command="password" divided>修改口令</el-dropdown-item>
        <el-dropdown-item command="logout">退出登录</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>

  <el-dialog v-model="pwdVisible" title="修改口令" width="400px" append-to-body>
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
.user-chip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  padding: 0 var(--space-2) 0 var(--space-1);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: none;
  color: var(--text-primary);
  font: inherit;
  cursor: pointer;
}
.user-chip:hover { border-color: var(--border); background: var(--bg-subtle); }
.user-chip:focus-visible { outline: 2px solid var(--brand-300); outline-offset: 1px; }
.avatar {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-50);
  color: var(--brand-700);
  font-size: var(--fs-13);
  font-weight: var(--fw-semibold);
}
.user-text { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.2; }
.user-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-13);
  font-weight: var(--fw-medium);
}
.user-role { font-size: var(--fs-12); color: var(--text-secondary); }
.caret { color: var(--text-secondary); }
</style>
