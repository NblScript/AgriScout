<script setup lang="ts">
/** 用户管理（仅管理员，决策 D15）：建号、改角色、停用启用、重置口令。不提供删除——停用即可，历史署名不悬空。 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import { usersApi } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { ROLE_LABELS, type User, type UserRole } from '../types'
import { fieldClock } from '../utils/fieldTime'

const auth = useAuthStore()
const users = ref<User[]>([])
const loading = ref(false)
const ROLE_TAG: Record<UserRole, 'danger' | 'primary' | 'info'> = { admin: 'danger', operator: 'primary', viewer: 'info' }
const ROLE_OPTIONS = (Object.keys(ROLE_LABELS) as UserRole[]).map((value) => ({ value, label: ROLE_LABELS[value] }))
const ROLE_HELP: Record<UserRole, string> = {
  admin: '全部功能 + 用户管理',
  operator: '地块、巡检、复核、审批等业务读写',
  viewer: '只能查看，不能修改数据（适合展示或评审账号）',
}

async function load() {
  loading.value = true
  try {
    users.value = await usersApi.list()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

/* ---------- 新建 ---------- */
const dialogVisible = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({ username: '', display_name: '', password: '', role: 'operator' as UserRole })
const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_.-]{3,50}$/, message: '3–50 位字母、数字、下划线、点或连字符', trigger: 'blur' },
  ],
  display_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: '口令至少 8 位', trigger: 'blur' }],
}
const saving = ref(false)

function openCreate() {
  Object.assign(form, { username: '', display_name: '', password: '', role: 'operator' })
  dialogVisible.value = true
}

async function submitCreate() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    await usersApi.create({ ...form, username: form.username.trim(), display_name: form.display_name.trim() })
    ElMessage.success('用户已创建')
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

/* ---------- 行内操作 ---------- */
async function changeRole(row: User, role: UserRole) {
  try {
    await usersApi.update(row.id, { role })
    ElMessage.success(`${row.display_name} 的角色已改为${ROLE_LABELS[role]}`)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
  await load()
}

async function toggleActive(row: User) {
  const next = !row.is_active
  try {
    if (!next) await ElMessageBox.confirm(`停用后 ${row.display_name} 将立即无法访问平台，确认停用？`, '停用账号', { type: 'warning' })
    await usersApi.update(row.id, { is_active: next })
    ElMessage.success(next ? '已启用' : '已停用')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
  await load()
}

async function resetPassword(row: User) {
  try {
    const { value } = await ElMessageBox.prompt(`为 ${row.display_name}（${row.username}）设置新口令`, '重置口令', {
      inputType: 'password', inputPattern: /^.{8,}$/, inputErrorMessage: '口令至少 8 位',
    })
    await usersApi.update(row.id, { password: value })
    ElMessage.success('口令已重置，请线下告知本人并提醒登录后修改')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(errMsg(e))
  }
}

const fmtTime = (v: string | null) => fieldClock(v)

onMounted(load)
</script>

<template>
  <PageHeader title="用户管理" subtitle="账号由管理员分配，不开放注册；不提供删除，离开团队的成员请停用">
    <template #actions>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </template>
  </PageHeader>

  <SectionCard flush>
    <el-table :data="users" v-loading="loading">
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="display_name" label="姓名" min-width="120" />
      <el-table-column label="角色" width="150">
        <template #default="{ row }">
          <el-select :model-value="row.role" size="small" :disabled="row.id === auth.user?.id"
                     @change="(role: UserRole) => changeRole(row, role)">
            <el-option v-for="o in ROLE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" effect="plain">{{ row.is_active ? '启用' : '已停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近登录" min-width="160"><template #default="{ row }">{{ fmtTime(row.last_login_at) }}</template></el-table-column>
      <el-table-column label="创建时间" min-width="160"><template #default="{ row }">{{ fmtTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="resetPassword(row)">重置口令</el-button>
          <el-button size="small" text :type="row.is_active ? 'danger' : 'success'" :disabled="row.id === auth.user?.id"
                     @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
        </template>
      </el-table-column>
    </el-table>
  </SectionCard>

  <SectionCard title="角色说明" class="roles">
    <div v-for="o in ROLE_OPTIONS" :key="o.value" class="role-row">
      <el-tag :type="ROLE_TAG[o.value]" effect="plain" size="small">{{ o.label }}</el-tag>
      <span>{{ ROLE_HELP[o.value] }}</span>
    </div>
  </SectionCard>

  <el-dialog v-model="dialogVisible" title="新建用户" width="440px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="72px">
      <el-form-item label="用户名" prop="username"><el-input v-model="form.username" autocomplete="off" /></el-form-item>
      <el-form-item label="姓名" prop="display_name"><el-input v-model="form.display_name" placeholder="复核、审批记录里显示的名字" /></el-form-item>
      <el-form-item label="初始口令" prop="password">
        <el-input v-model="form.password" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item label="角色">
        <el-radio-group v-model="form.role">
          <el-radio-button v-for="o in ROLE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</el-radio-button>
        </el-radio-group>
        <p class="dim help">{{ ROLE_HELP[form.role] }}</p>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submitCreate">创建</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.dim { color: var(--text-secondary); font-size: var(--fs-12); }
.help { margin: 4px 0 0; width: 100%; }
.roles { margin-top: var(--space-4); }
.role-row { display: flex; gap: var(--space-3); align-items: center; padding: var(--space-1) 0; font-size: var(--fs-13); color: var(--text-regular); }
</style>
