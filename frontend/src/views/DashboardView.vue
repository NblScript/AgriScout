<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
  <section class="card">
    <h2>系统状态</h2>
    <p v-if="loading" class="status loading">⏳ 正在连接后端…</p>
    <template v-else-if="health">
      <p class="status ok">✅ 系统在线</p>
      <dl class="grid">
        <div><dt>应用</dt><dd>{{ health.app }}</dd></div>
        <div><dt>版本</dt><dd>v{{ health.version }}</dd></div>
        <div><dt>环境</dt><dd>{{ health.environment }}</dd></div>
        <div>
          <dt>数据库</dt>
          <dd :class="health.database === 'ok' ? 'ok-text' : 'err-text'">
            {{ health.database === 'ok' ? '连接正常' : '异常' }}
          </dd>
        </div>
      </dl>
      <el-button type="primary" plain @click="fetchHealth">重新检测</el-button>
    </template>
    <p v-else class="status err">
      ❌ 后端不可达（{{ error }}）——请先启动后端：<code>cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000</code>
    </p>
  </section>
</template>

<style scoped>
.card {
  background: #fff;
  border: 1px solid #e2e8e2;
  border-radius: 12px;
  padding: 24px;
}
.card h2 {
  font-size: 18px;
  margin-bottom: 16px;
}
.status {
  font-size: 16px;
  margin-bottom: 16px;
}
.status.ok { color: #2e7d32; }
.status.err { color: #c62828; }
.status.loading { color: #6b7a6b; }
.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.grid dt { font-size: 12px; color: #8a978a; }
.grid dd { font-size: 15px; margin-top: 2px; }
.ok-text { color: #2e7d32; }
.err-text { color: #c62828; }
code {
  background: #f0f3f0;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
