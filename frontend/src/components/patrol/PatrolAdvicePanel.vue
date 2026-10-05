<script setup lang="ts">
/**
 * 巡检回放的农事建议（规则引擎，可溯源到规则快照），折叠分区之一：按状态筛选，采纳 / 驳回，按当前规则重算。
 * 写操作只读账号看不到。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { advicesApi } from '../../api'
import { errMsg } from '../../api/http'
import { useAuthStore } from '../../stores/auth'
import { ADVICE_STATUS_LABELS, type Advice, type AdviceStatus, type CapturePointFull } from '../../types'

const props = defineProps<{ patrolId: number; points: CapturePointFull[] }>()
const auth = useAuthStore()

const advices = ref<Advice[]>([])
const loading = ref(false)
const filter = ref<AdviceStatus | ''>('')
const filtered = computed(() => (filter.value ? advices.value.filter((a) => a.status === filter.value) : advices.value))
const pending = computed(() => advices.value.filter((a) => a.status === 'suggested').length)
const seqByPointId = computed(() => new Map(props.points.map((p) => [p.id, p.seq])))

async function load() {
  loading.value = true
  try {
    advices.value = (await advicesApi.list(props.patrolId)).items
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function decide(advice: Advice, status: Exclude<AdviceStatus, 'suggested'>) {
  try {
    const updated = await advicesApi.setStatus(advice.id, status)
    const idx = advices.value.findIndex((a) => a.id === updated.id)
    if (idx >= 0) advices.value[idx] = updated
    ElMessage.success(`建议已${ADVICE_STATUS_LABELS[status]}`)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function regenerate() {
  try {
    await ElMessageBox.confirm('重新生成会清理「待处理」建议并按当前规则重算；已采纳 / 驳回的记录保留。继续？', '重算建议', { type: 'warning' })
  } catch { return }
  try {
    const stats = await advicesApi.generate(props.patrolId)
    ElMessage.success(`已重算：新增 ${stats.created} 条（保护已决策的 ${stats.skipped_decided} 条）`)
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

function priorityType(priority: string): 'danger' | 'warning' | 'info' {
  return priority === 'high' ? 'danger' : priority === 'medium' ? 'warning' : 'info'
}
const PRIORITY_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' }
</script>

<template>
  <el-collapse-item name="advice">
    <template #title>
      <span class="title">农事建议</span>
      <span class="muted text-12 sub">可溯源到规则 · 共 {{ advices.length }} 条<template v-if="pending">，待处理 {{ pending }}</template></span>
      <span v-if="!auth.isViewer" class="actions" @click.stop>
        <el-button size="small" @click="regenerate">重算建议</el-button>
      </span>
    </template>
    <el-radio-group v-model="filter" size="small" class="filter">
      <el-radio-button value="">全部 {{ advices.length }}</el-radio-button>
      <el-radio-button value="suggested">待处理 {{ pending }}</el-radio-button>
      <el-radio-button value="accepted">已采纳</el-radio-button>
      <el-radio-button value="rejected">已驳回</el-radio-button>
    </el-radio-group>
    <el-table :data="filtered" v-loading="loading" size="small" max-height="360">
      <el-table-column label="点" width="64">
        <template #default="{ row }">{{ row.capture_point_id != null ? `#${seqByPointId.get(row.capture_point_id) ?? '?'}` : '—' }}</template>
      </el-table-column>
      <el-table-column label="优先级" width="80">
        <template #default="{ row }">
          <el-tag :type="priorityType(row.priority)" size="small" effect="plain">{{ PRIORITY_LABELS[row.priority] ?? row.priority }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="content" label="建议内容" min-width="300" show-overflow-tooltip />
      <el-table-column label="规则依据" width="150">
        <template #default="{ row }">
          <el-tooltip placement="top">
            <template #content>
              规则 {{ row.rule_snapshot.rule_key }} v{{ row.rule_snapshot.version }}<br>
              层级：{{ row.rule_snapshot.tier }} · 条件：{{ JSON.stringify(row.rule_snapshot.condition) }}<br>
              出处：{{ row.rule_snapshot.source || '—' }}
            </template>
            <span class="rule">{{ row.rule_snapshot.rule_key }} v{{ row.rule_snapshot.version }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="row.status === 'accepted' ? 'success' : row.status === 'rejected' ? 'danger' : 'primary'">
            {{ ADVICE_STATUS_LABELS[row.status as AdviceStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="!auth.isViewer" label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'suggested'">
            <el-button size="small" type="success" plain @click="decide(row, 'accepted')">采纳</el-button>
            <el-button size="small" type="danger" plain @click="decide(row, 'rejected')">驳回</el-button>
          </template>
          <span v-else class="muted text-12">已决策</span>
        </template>
      </el-table-column>
      <template #empty>
        <span class="muted text-13">没有建议{{ auth.isViewer ? '' : '：分析完成后点「重算建议」' }}</span>
      </template>
    </el-table>
  </el-collapse-item>
</template>

<style scoped>
.title { font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text-primary); }
.sub { margin-left: var(--space-2); }
.actions { margin-left: auto; padding-right: var(--space-3); }
.filter { margin-bottom: var(--space-3); }
.rule { cursor: help; border-bottom: 1px dashed var(--neutral-400); font-size: var(--fs-12); color: var(--text-regular); }
</style>
