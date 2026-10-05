<script setup lang="ts">
/** 规则修订审批页：Agent 起草 → 影子 diff → 人工批/驳（规则线 L1 的人工闸门）。 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import { ruleRevisionApi } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { RuleRevision } from '../types'
import { fieldClock } from '../utils/fieldTime'

const revisions = ref<RuleRevision[]>([])
const loading = ref(true)
const generating = ref(false)
const auth = useAuthStore()
const decidedBy = ref(auth.user?.display_name ?? readAnnotator())
function readAnnotator(): string {
  try { return localStorage.getItem('agriscout_annotator') ?? '' } catch { return '' }
}
const statusFilter = ref<'' | 'draft' | 'approved' | 'rejected'>('')
/** per-revision 操作锁：影子/审批进行中的按钮防重入 */
const opLoading = ref<Record<number, boolean>>({})

function setOp(id: number, busy: boolean) {
  if (busy) opLoading.value = { ...opLoading.value, [id]: true }
  else {
    const next = { ...opLoading.value }
    delete next[id]
    opLoading.value = next
  }
}

async function load() {
  loading.value = true
  try {
    revisions.value = await ruleRevisionApi.list(statusFilter.value || undefined)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function generate() {
  generating.value = true
  try {
    const r = await ruleRevisionApi.generate()
    ElMessage.success(`起草完成：${r.created} 条修订案`)
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    generating.value = false
  }
}

async function shadow(rev: RuleRevision) {
  setOp(rev.id, true)
  try {
    const updated = await ruleRevisionApi.shadow(rev.id)
    Object.assign(rev, updated)
    const sr = updated.shadow_result
    ElMessage.info(
      `影子完成：${sr?.added_total} 条新增 / ${sr?.removed_total} 条消失（${sr?.patrols_checked.length} 场巡检）`,
    )
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    setOp(rev.id, false)
  }
}

async function decide(rev: RuleRevision, action: 'approve' | 'reject') {
  const isApprove = action === 'approve'
  try {
    await ElMessageBox.confirm(
      isApprove
        ? `批准后立即写入规则表（version+1）并生效。影子 diff：新增 ${rev.shadow_result?.added_total ?? '?'} / 消失 ${rev.shadow_result?.removed_total ?? '?'}。继续？`
        : `驳回后归档留痕，不影响现规则。继续？`,
      isApprove ? '批准修订案' : '驳回修订案',
      { type: isApprove ? 'warning' : 'info' },
    )
  } catch { return }
  setOp(rev.id, true)
  try {
    const updated = await ruleRevisionApi.decide(rev.id, action, {
      decided_by: decidedBy.value.trim() || '未署名',
    })
    Object.assign(rev, updated)
    ElMessage.success(isApprove ? `已生效（规则 v${updated.applied_version}）` : '已驳回归档')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    setOp(rev.id, false)
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="规则修订审批" subtitle="Agent 起草 · 影子验证 · 人工批准后才生效；批准的修订案须回写规则 YAML">
    <template #actions>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      <template v-if="!auth.isViewer">
        <el-input v-model="decidedBy" placeholder="审批人姓名" class="decider" />
        <el-button type="primary" :loading="generating" @click="generate">触发起草</el-button>
      </template>
    </template>
  </PageHeader>

  <div v-loading="loading">
    <div class="filter-row">
      <el-radio-group v-model="statusFilter" size="small" @change="load">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="draft">待审</el-radio-button>
        <el-radio-button value="approved">已生效</el-radio-button>
        <el-radio-button value="rejected">已驳回</el-radio-button>
      </el-radio-group>
    </div>

    <el-alert
      type="info" :closable="false" show-icon
      title="流程说明：起草 Agent 分析建议采纳/驳回与复核标注数据 → 产出修订案 → 影子运行对比新旧规则效果 → 人工批准后写入规则表（版本+1）。驳回的修订案归档留痕。"
      style="margin-bottom: 12px"
    />

    <EmptyState v-if="!revisions.length && !loading" title="暂无修订案" :description="auth.isViewer ? '' : '点右上角「触发起草」'" />

    <div class="cards">
      <div v-for="rev in revisions" :key="rev.id">
        <div class="rev-card" :class="rev.status">
          <div class="rev-head">
            <el-tag
              :type="rev.status === 'approved' ? 'success' : rev.status === 'rejected' ? 'danger' : 'warning'"
              size="small"
            >
              {{ rev.status === 'approved' ? '已生效' : rev.status === 'rejected' ? '已驳回' : '待审' }}
            </el-tag>
            <b>{{ rev.rule_key }}</b>
            <el-tag size="small" effect="plain">{{ rev.action === 'modify' ? '修改' : rev.action === 'add' ? '新增' : '停用' }}</el-tag>
            <span class="dim">{{ rev.model }} · {{ fieldClock(rev.created_at) }}</span>
          </div>

          <div class="section">
            <span class="label">起草理由</span>
            <p class="reason">{{ rev.reason }}</p>
          </div>

          <div class="section">
            <span class="label">修订后规则</span>
            <pre class="draft-json">{{ JSON.stringify(rev.draft, null, 1) }}</pre>
          </div>

          <div class="section" v-if="rev.shadow_result">
            <span class="label">影子运行 diff</span>
            <div class="shadow">
              <span>检查 {{ rev.shadow_result.patrols_checked.length }} 场巡检</span>
              <span class="added">+{{ rev.shadow_result.added_total }} 新增建议</span>
              <span class="removed">-{{ rev.shadow_result.removed_total }} 消失</span>
            </div>
          </div>
          <div class="section" v-else-if="rev.status === 'draft'">
            <span class="label">影子运行</span>
            <p class="dim">未执行——批准前必须先跑影子对比</p>
          </div>

          <div class="ops" v-if="rev.status === 'draft' && !auth.isViewer">
            <el-button size="small" :loading="!!opLoading[rev.id]" @click="shadow(rev)">影子运行</el-button>
            <el-button
              size="small" type="success"
              :disabled="!rev.shadow_result || !!opLoading[rev.id]" :loading="!!opLoading[rev.id]"
              @click="decide(rev, 'approve')"
            >
              批准生效
            </el-button>
            <el-button size="small" type="danger" plain :disabled="!!opLoading[rev.id]" @click="decide(rev, 'reject')">驳回</el-button>
          </div>
          <div class="ops" v-else-if="rev.status !== 'draft'">
            <span class="dim">{{ rev.decided_by }} · {{ rev.decide_note || '无备注' }}
              <template v-if="rev.applied_version"> · 已应用为规则 v{{ rev.applied_version }}</template>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.decider { width: 140px; }
.filter-row { margin-bottom: var(--space-3); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 480px), 1fr)); gap: var(--space-4); margin-top: var(--space-4); }
.dim { color: var(--text-secondary); font-size: var(--fs-12); }
.rev-card {
  height: 100%;
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  box-shadow: var(--shadow-1);
}
.rev-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.section { margin: var(--space-2) 0; }
.label { font-size: var(--fs-12); color: var(--text-secondary); }
.reason { margin: var(--space-1) 0; font-size: var(--fs-13); color: var(--text-primary); }
/* 不能叫 .draft：卡片带状态类名 draft，会把整张待审卡片截成 180px */
.draft-json {
  max-height: 180px;
  margin: var(--space-1) 0 0;
  padding: var(--space-2);
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  font-family: var(--font-mono);
  font-size: 11px;
}
.shadow { display: flex; gap: var(--space-4); margin-top: var(--space-1); font-size: var(--fs-13); }
.shadow .added { color: var(--success-ink); }
.shadow .removed { color: var(--danger-ink); }
.ops { display: flex; align-items: center; gap: var(--space-2); margin-top: var(--space-3); }
.rev-card.rejected { opacity: 0.65; }
</style>
