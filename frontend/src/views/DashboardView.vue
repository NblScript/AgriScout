<script setup lang="ts">
/** 系统状态：后端健康检查（公开接口 /health）。计划 0018 阶段 B 换外壳，表情符号换成图标 + 文字。 */
import { onMounted, ref } from 'vue'
import { CircleCheckFilled, CircleCloseFilled, Refresh } from '@element-plus/icons-vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import { errMsg } from '../api/http'

interface HealthInfo {
  status: string
  app: string
  version: string
  environment: string
  database: string
}

const health = ref<HealthInfo | null>(null)
const error = ref('')
const loading = ref(true)

async function fetchHealth() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/v1/health')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    health.value = (await resp.json()) as HealthInfo
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

onMounted(fetchHealth)
</script>

<template>
  <PageHeader title="系统状态" subtitle="后端服务和数据库是否在线">
    <template #actions>
      <el-button :icon="Refresh" :loading="loading" @click="fetchHealth">重新检测</el-button>
    </template>
  </PageHeader>

  <SectionCard>
    <el-skeleton v-if="loading && !health" animated :rows="2" />
    <template v-else-if="health">
      <p class="status ok"><el-icon><CircleCheckFilled /></el-icon>系统在线</p>
      <dl class="grid">
        <div><dt>应用</dt><dd>{{ health.app }}</dd></div>
        <div><dt>版本</dt><dd class="tabular">v{{ health.version }}</dd></div>
        <div><dt>环境</dt><dd>{{ health.environment }}</dd></div>
        <div>
          <dt>数据库</dt>
          <dd :class="health.database === 'ok' ? 'ok-text' : 'err-text'">{{ health.database === 'ok' ? '连接正常' : '异常' }}</dd>
        </div>
      </dl>
    </template>
    <div v-else class="status err">
      <p><el-icon><CircleCloseFilled /></el-icon>后端不可达（{{ error }}）</p>
      <p class="hint">请先启动后端：<code>cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000</code></p>
    </div>
  </SectionCard>
</template>

<style scoped>
.status { margin: 0 0 var(--space-4); font-size: var(--fs-16); font-weight: var(--fw-medium); }
.status p { margin: 0; }
.status p:first-child, p.status { display: flex; align-items: center; gap: var(--space-2); }
.status.ok { color: var(--success-ink); }
.status.err { color: var(--danger-ink); }
.hint { margin-top: var(--space-2) !important; font-size: var(--fs-13); font-weight: var(--fw-regular); color: var(--text-secondary); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--space-4); margin: 0; }
.grid dt { font-size: var(--fs-12); color: var(--text-secondary); }
.grid dd { margin: 2px 0 0; font-size: var(--fs-16); color: var(--text-primary); }
.ok-text { color: var(--success-ink); }
.err-text { color: var(--danger-ink); }
code { padding: 2px 6px; border-radius: var(--radius-sm); background: var(--bg-subtle); font-family: var(--font-mono); }
</style>
