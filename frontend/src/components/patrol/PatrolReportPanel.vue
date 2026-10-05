<script setup lang="ts">
/** 巡检回放的 AI 农事报告（建议线 L1），折叠分区之一：没生成过时可生成，生成过可重新生成；只读账号只看。 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { reportsApi } from '../../api'
import { errMsg, isNotFound } from '../../api/http'
import { useAuthStore } from '../../stores/auth'
import type { PatrolReport } from '../../types'
import { fieldClock } from '../../utils/fieldTime'

const props = defineProps<{ patrolId: number }>()
const auth = useAuthStore()

const report = ref<PatrolReport | null>(null)
const loadError = ref('')
const generating = ref(false)

async function load() {
  try {
    report.value = await reportsApi.get(props.patrolId)
    loadError.value = ''
  } catch (e) {
    // 404 = 还没生成，不是错误
    loadError.value = isNotFound(e) ? '' : errMsg(e)
  }
}
onMounted(load)

async function generate() {
  generating.value = true
  try {
    await reportsApi.generate(props.patrolId)
    await load()
    ElMessage.success('AI 报告已生成')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    generating.value = false
  }
}

/** 轻量 markdown 渲染：先转义，再支持 ## 标题 / - 列表 / **粗体**（够报告用，不引库） */
function mdToHtml(src: string): string {
  const esc = src.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return esc.split('\n').map((line) => {
    const bold = line.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    if (bold.startsWith('## ')) return `<h4>${bold.slice(3)}</h4>`
    if (bold.startsWith('# ')) return `<h4>${bold.slice(2)}</h4>`
    if (/^[-*] /.test(bold)) return `<li>${bold.slice(2)}</li>`
    return bold.trim() ? `<p>${bold}</p>` : ''
  }).join('\n')
}
</script>

<template>
  <el-collapse-item name="report">
    <template #title>
      <span class="title">AI 农事报告</span>
      <span class="muted text-12 sub">
        <template v-if="report">{{ report.model }} · prompt {{ report.prompt_version }} · {{ fieldClock(report.updated_at) }}</template>
        <template v-else>还没生成</template>
      </span>
      <span v-if="!auth.isViewer" class="actions" @click.stop>
        <el-button size="small" :type="report ? 'default' : 'primary'" :plain="!report" :loading="generating" @click="generate">
          {{ report ? '重新生成' : '生成 AI 报告' }}
        </el-button>
      </span>
    </template>
    <div v-if="report" class="body" v-html="mdToHtml(report.content)" />
    <p v-else-if="loadError" class="muted text-13 none">报告没取到：{{ loadError }}</p>
    <p v-else class="muted text-13 none">
      还没生成。分析完成后可由大模型基于规则命中结果撰写（需在 backend/.env 配置 LLM_API_BASE/KEY/MODEL）。
    </p>
  </el-collapse-item>
</template>

<style scoped>
.title { font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text-primary); }
.sub { margin-left: var(--space-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actions { margin-left: auto; padding-right: var(--space-3); }
.body { font-size: var(--fs-14); line-height: 1.7; color: var(--text-primary); }
.body :deep(h4) { margin: var(--space-3) 0 var(--space-1); font-size: var(--fs-14); }
.body :deep(p) { margin: var(--space-1) 0; }
.body :deep(li) { margin: 2px 0 2px 18px; }
.none { margin: 0; }
</style>
