<script setup lang="ts">
/** 登录页（决策 D15；计划 0018 换新视觉）：账号由管理员分配，不开放注册。 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import StateTag from '../components/ui/StateTag.vue'
import TaskTypeTag from '../components/ui/TaskTypeTag.vue'
import { errMsg } from '../api/http'
import { HOME_PATH } from '../router'
import { useAuthStore } from '../stores/auth'
import type { PlanListName, PlantStateValue } from '../types'

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
      ? target : HOME_PATH
    await router.replace(redirect)
  } catch (e) {
    error.value = errMsg(e)
    form.password = ''
  } finally {
    submitting.value = false
  }
}

/* 左侧示意：「垄 × 株」状态网格的缩略图（固定种子，非真实数据） */
const ROWS = 8
const COLS = 28
const STATES: PlantStateValue[] = ['healthy', 'early', 'symptomatic', 'unknown']
const TASKS: PlanListName[] = ['confirm', 'reshoot', 'coverage', 'random']
const cells = (() => {
  let seed = 20261003
  const rand = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648)
  return Array.from({ length: ROWS * COLS }, (_, index) => {
    const r = rand()
    const state: PlantStateValue = r < 0.015 ? 'symptomatic' : r < 0.05 ? 'early' : r < 0.11 ? 'unknown' : 'healthy'
    const t = rand()
    let task: PlanListName | '' = ''
    if (state === 'early' || state === 'symptomatic') task = t < 0.5 ? 'confirm' : t < 0.8 ? 'reshoot' : ''
    else if (state === 'unknown') task = t < 0.4 ? 'coverage' : ''
    else if (t < 0.03) task = 'reshoot'
    else if (t < 0.045) task = 'random'
    return { index, state, task }
  })
})()
</script>

<template>
  <div class="login-page">
    <div class="login-shell">
      <section class="intro">
        <div class="brand">
          <span class="logo" aria-hidden="true">巡</span>
          <span class="brand-text"><b>巡知</b><small>AgriScout</small></span>
        </div>
        <h1>设施大棚病害主动巡检平台</h1>
        <p class="lead">小车沿垄近地拍叶背，平台按株记录状态，结合棚内温湿度安排每天该看哪些株、哪些株推给人确认。</p>

        <figure class="preview" aria-label="「垄 × 株」状态网格示意">
          <div class="grid" :style="{ gridTemplateColumns: `repeat(${COLS}, 1fr)` }">
            <i v-for="cell in cells" :key="cell.index" class="cell" :class="[`s-${cell.state}`, cell.task && `t-${cell.task}`]" />
          </div>
          <figcaption>
            <span class="legend">
              <StateTag v-for="s in STATES" :key="s" :state="s" size="small" />
            </span>
            <span class="legend">
              <TaskTypeTag v-for="t in TASKS" :key="t" :type="t" />
            </span>
          </figcaption>
        </figure>

        <ul class="points">
          <li><b>按株建档</b><span>株号贯穿照片、状态和任务，每株一条时间线</span></li>
          <li><b>环境驱动</b><span>温湿度算霜霉病环境风险，安排清晨叶背补拍</span></li>
          <li><b>人工把关</b><span>模型只做推荐，人确认后的结论才进数据集</span></li>
        </ul>
      </section>

      <section class="form-panel">
        <div class="form-head">
          <h2>登录</h2>
          <p>使用平台管理员分配的账号</p>
        </div>

        <el-alert v-if="expired && !error" type="info" :closable="false" show-icon title="登录已过期，请重新登录" class="tip" />
        <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" class="tip" />

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large" @submit.prevent="submit">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" :prefix-icon="User" autocomplete="username" autofocus placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="口令" prop="password">
            <el-input v-model="form.password" :prefix-icon="Lock" type="password" autocomplete="current-password" show-password
                      placeholder="请输入口令" @keyup.enter="submit" />
          </el-form-item>
          <el-button type="primary" class="submit" :loading="submitting" native-type="submit">登录</el-button>
        </el-form>

        <p class="hint">不开放注册；忘记口令请联系管理员重置。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6) var(--space-4);
  background: var(--bg-page);
}
.login-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  width: 100%;
  max-width: 1040px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-2);
  overflow: hidden;
}

/* ---------- 左：产品说明 ---------- */
.intro {
  padding: var(--space-6) var(--space-6) var(--space-5);
  background: var(--bg-subtle);
  border-right: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: var(--space-3); }
.logo {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-600);
  color: #fff;
  font-size: var(--fs-20);
  font-weight: var(--fw-semibold);
}
.brand-text { display: flex; flex-direction: column; line-height: 1.2; }
.brand-text b { font-size: var(--fs-16); color: var(--text-primary); }
.brand-text small { font-size: var(--fs-12); color: var(--text-secondary); letter-spacing: 0.02em; }
.intro h1 {
  margin: var(--space-6) 0 var(--space-2);
  font-size: var(--fs-30);
  line-height: var(--lh-30);
  font-weight: var(--fw-semibold);
  color: var(--text-primary);
}
.lead { margin: 0; max-width: 520px; font-size: var(--fs-14); line-height: var(--lh-14); color: var(--text-regular); }

.preview {
  margin: var(--space-5) 0 0;
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.grid { display: grid; gap: 4px; }
.cell {
  display: block;
  aspect-ratio: 1;
  border-radius: 2px;
  background: var(--state-healthy);
}
.s-early { background: var(--state-early); }
.s-symptomatic { background: var(--state-symptomatic); }
.s-unknown {
  background: repeating-linear-gradient(135deg, var(--state-unknown) 0 3px, var(--neutral-100) 3px 5px);
  box-shadow: inset 0 0 0 1px var(--neutral-300);
}
/* 今日任务：任务色描边 + 线型 */
.cell[class*='t-'] { outline-offset: 1px; }
.t-confirm { outline: 2px var(--task-confirm-line) var(--task-confirm); }
.t-reshoot { outline: 2px var(--task-reshoot-line) var(--task-reshoot); }
.t-coverage { outline: 2px var(--task-coverage-line) var(--task-coverage); }
.t-random { outline: 3px var(--task-random-line) var(--task-random); }
.preview figcaption { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-4); }
.legend { display: flex; flex-wrap: wrap; gap: var(--space-2); }

.points { list-style: none; margin: var(--space-5) 0 0; padding: 0; display: grid; gap: var(--space-2); }
.points li { display: flex; gap: var(--space-3); font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-regular); }
.points b { flex: none; width: 4.5em; color: var(--text-primary); font-weight: var(--fw-semibold); }

/* ---------- 右：登录表单 ---------- */
.form-panel { display: flex; flex-direction: column; justify-content: center; padding: var(--space-6); }
.form-head { margin-bottom: var(--space-5); }
.form-head h2 { margin: 0; font-size: var(--fs-24); line-height: var(--lh-24); font-weight: var(--fw-semibold); }
.form-head p { margin: var(--space-1) 0 0; font-size: var(--fs-14); color: var(--text-secondary); }
.tip { margin-bottom: var(--space-4); }
.submit { width: 100%; margin-top: var(--space-2); }
.hint { margin: var(--space-5) 0 0; font-size: var(--fs-12); color: var(--text-secondary); text-align: center; }

@media (max-width: 860px) {
  .login-shell { grid-template-columns: 1fr; max-width: 440px; }
  .intro { border-right: none; border-bottom: 1px solid var(--border); padding: var(--space-5); }
  .intro h1 { margin-top: var(--space-4); font-size: var(--fs-20); line-height: var(--lh-20); }
  .preview, .points { display: none; }
  .form-panel { padding: var(--space-5); }
}
</style>
