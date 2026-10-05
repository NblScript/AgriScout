<script setup lang="ts">
/** 巡检回放的「问一问」（建议线 L2 诊断 Agent，只读查询平台数据），折叠分区之一。提问要调模型，只读账号不能用。 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { agentApi } from '../../api'
import { errMsg } from '../../api/http'
import { useAuthStore } from '../../stores/auth'

const props = defineProps<{ patrolId: number }>()
const auth = useAuthStore()

interface ChatTurn {
  question: string
  answer: string
  trace: { tool: string; arguments: Record<string, unknown> }[]
  model?: string
}
const turns = ref<ChatTurn[]>([])
const input = ref('')
const loading = ref(false)

async function ask() {
  const q = input.value.trim()
  if (!q || loading.value) return
  loading.value = true
  input.value = ''
  try {
    const r = await agentApi.chat(q, props.patrolId)
    turns.value.push({ question: q, answer: r.answer, trace: r.tool_calls_trace, model: r.model })
  } catch (e) {
    ElMessage.error(errMsg(e))
    input.value = q
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-collapse-item name="ask">
    <template #title>
      <span class="title">问一问</span>
      <span class="muted text-12 sub">诊断 Agent · 只读查询平台数据<template v-if="turns.length"> · {{ turns.length }} 轮</template></span>
    </template>
    <div v-if="turns.length" class="log">
      <div v-for="(t, i) in turns" :key="i" class="turn">
        <div class="q">问：{{ t.question }}</div>
        <div class="a">{{ t.answer }}</div>
        <el-collapse v-if="t.trace.length" class="trace">
          <el-collapse-item :title="`调用了 ${t.trace.length} 次数据工具（点开看溯源）`">
            <div v-for="(c, j) in t.trace" :key="j" class="trace-line"><code>{{ c.tool }}</code> {{ JSON.stringify(c.arguments) }}</div>
            <div class="muted text-12">模型：{{ t.model }}</div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
    <p v-if="auth.isViewer" class="muted text-13 none">只读账号不能提问（问一问会调用模型），可以请操作员或管理员来问。</p>
    <div v-else class="input-row">
      <el-input v-model="input" placeholder="例如：这次巡检哪里风险最高？依据是什么？" maxlength="500" :disabled="loading" @keyup.enter="ask" />
      <el-button type="primary" :loading="loading" @click="ask">提问</el-button>
    </div>
  </el-collapse-item>
</template>

<style scoped>
.title { font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text-primary); }
.sub { margin-left: var(--space-2); }
.log { display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-3); }
.turn { padding-left: var(--space-3); border-left: 3px solid var(--border-strong); }
.q { font-size: var(--fs-13); color: var(--text-secondary); }
.a { margin-top: var(--space-1); font-size: var(--fs-14); line-height: 1.7; color: var(--text-primary); white-space: pre-wrap; }
.trace { margin-top: var(--space-1); border: 0; }
.trace :deep(.el-collapse-item__header) { height: 30px; font-size: var(--fs-12); color: var(--text-secondary); border: 0; }
.trace :deep(.el-collapse-item__wrap) { border: 0; }
.trace-line { margin: 2px 0; font-size: var(--fs-12); color: var(--text-regular); word-break: break-all; }
.trace-line code { padding: 1px 5px; border-radius: 3px; background: var(--bg-subtle); }
.none { margin: 0; }
.input-row { display: flex; gap: var(--space-2); }
</style>
