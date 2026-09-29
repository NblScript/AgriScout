<script setup lang="ts">
/** 登录页（决策 D15）：账号由管理员分配，不开放注册。 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入口令', trigger: 'blur' }],
}
const submitting = ref(false)
const error = ref('')
const expired = route.query.reason === 'expired'

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  submitting.value = true
  error.value = ''
  try {
    await auth.login(form.username.trim(), form.password)
    // 只接受站内路径（以单个 / 开头），防止 //外站 形式的跳转
    const target = route.query.redirect
    const redirect = typeof target === 'string' && target.startsWith('/') && !target.startsWith('//')
      ? target : '/dashboard'
    await router.replace(redirect)
  } catch (e) {
    error.value = errMsg(e)
    form.password = ''
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <i class="brand-dot" />
        <div>
          <h1>巡知 · AgriScout</h1>
          <p>农田巡检与复巡决策平台</p>
        </div>
      </div>

      <el-alert v-if="expired && !error" type="info" :closable="false" show-icon title="登录已过期，请重新登录" class="tip" />
      <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" class="tip" />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large" @submit.prevent="submit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" autocomplete="username" autofocus placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="口令" prop="password">
          <el-input v-model="form.password" type="password" autocomplete="current-password" show-password
                    placeholder="请输入口令" @keyup.enter="submit" />
        </el-form-item>
        <el-button type="primary" class="submit" :loading="submitting" native-type="submit">登录</el-button>
      </el-form>

      <p class="hint">账号由平台管理员分配；忘记口令请联系管理员重置。</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: #f3f6f3;
}
.login-card {
  width: 100%;
  max-width: 380px;
  background: #fff;
  border: 1px solid #e2e8e2;
  border-radius: 12px;
  padding: 32px 32px 24px;
  box-shadow: 0 8px 24px rgba(31, 45, 31, 0.06);
}
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
.brand-dot { width: 14px; height: 14px; border-radius: 4px; background: var(--el-color-primary, #15803d); }
.brand h1 { font-size: 20px; font-weight: 600; color: #1f2d1f; margin: 0; }
.brand p { font-size: 12px; color: #8a978a; margin: 2px 0 0; }
.tip { margin-bottom: 16px; }
.submit { width: 100%; margin-top: 4px; }
.hint { margin: 16px 0 0; font-size: 12px; color: #9aa79a; text-align: center; }
</style>
