<script setup lang="ts">
import { onMounted, ref } from 'vue'

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
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(fetchHealth)
</script>

<template>
  <main class="page">
    <header class="header">
      <h1>🌾 AgriScout 农田巡检平台</h1>
      <p class="subtitle">农作物全生命周期管理系统 · M0 工程骨架</p>
    </header>

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
        <button class="refresh" @click="fetchHealth">重新检测</button>
      </template>
      <p v-else class="status err">
        ❌ 后端不可达（{{ error }}）——请确认后端已启动：<code>uvicorn app.main:app --port 8000</code>
      </p>
    </section>
  </main>
</template>

<style scoped>
.page {
  max-width: 720px;
  margin: 0 auto;
  padding: 48px 20px;
}
.header h1 {
  font-size: 28px;
  color: #2e5d34;
}
.subtitle {
  margin-top: 8px;
  color: #6b7a6b;
}
.card {
  margin-top: 32px;
  background: #fff;
  border: 1px solid #e2e8e2;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.card h2 {
  font-size: 18px;
  margin-bottom: 16px;
}
.status {
  font-size: 16px;
  margin-bottom: 16px;
}
.status.ok {
  color: #2e7d32;
}
.status.err {
  color: #c62828;
}
.status.loading {
  color: #6b7a6b;
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.grid dt {
  font-size: 12px;
  color: #8a978a;
}
.grid dd {
  font-size: 15px;
  margin-top: 2px;
}
.ok-text {
  color: #2e7d32;
}
.err-text {
  color: #c62828;
}
.refresh {
  padding: 8px 20px;
  border: 1px solid #2e5d34;
  background: #2e5d34;
  color: #fff;
  border-radius: 8px;
  cursor: pointer;
}
.refresh:hover {
  background: #274d2c;
}
code {
  background: #f0f3f0;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
