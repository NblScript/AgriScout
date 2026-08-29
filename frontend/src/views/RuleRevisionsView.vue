<script setup lang="ts">
/** 规则修订审批页：Agent 起草 → 影子 diff → 人工批/驳（规则线 L1 的人工闸门）。 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ruleRevisionApi } from '../api'
import type { RuleRevision } from '../types'

const revisions = ref<RuleRevision[]>([])
const loading = ref(true)
const generating = ref(false)
const decidedBy = ref(localStorage.getItem('agriscout_annotator') ?? '')
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
    ElMessage.error(e instanceof Error ? e.message : String(e))
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
    ElMessage.error(e instanceof Error ? e.message : String(e))
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
    ElMessage.error(e instanceof Error ? e.message : String(e))
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
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    setOp(rev.id, false)
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="head">
      <h3>规则修订审批 <span class="dim">（Agent 起草 · 影子验证 · 人工批准后才生效）</span></h3>
      <div class="head-right">
        <el-input
          v-model="decidedBy" placeholder="审批人姓名" style="width: 140px" size="small"
        />
        <el-button type="primary" :loading="generating" @click="generate">触发起草</el-button>
      </div>
    </div>

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

    <el-empty v-if="!revisions.length && !loading" description="暂无修订案——点击右上角「触发起草」" />

    <el-row :gutter="12">
      <el-col v-for="rev in revisions" :key="rev.id" :span="12" style="margin-bottom: 12px">
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
            <span class="dim">{{ rev.model }} · {{ new Date(rev.created_at).toLocaleString('zh-CN') }}</span>
          </div>

          <div class="section">
            <span class="label">起草理由</span>
            <p class="reason">{{ rev.reason }}</p>
          </div>

          <div class="section">
            <span class="label">修订后规则</span>
            <pre class="draft">{{ JSON.stringify(rev.draft, null, 1) }}</pre>
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

          <div class="ops" v-if="rev.status === 'draft'">
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
          <div class="ops" v-else>
            <span class="dim">{{ rev.decided_by }} · {{ rev.decide_note || '无备注' }}
              <template v-if="rev.applied_version"> · 已应用为规则 v{{ rev.applied_version }}</template>
            </span>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.head-right { display: flex; gap: 8px; }
.filter-row { margin-bottom: 12px; }
.dim { color: #9aa79a; font-size: 12px; }
.rev-card {
  background: #fff;
  border: 1px solid #e2e8e2;
  border-radius: 10px;
  padding: 12px;
  height: 100%;
}
.rev-head { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.section { margin: 8px 0; }
.label { font-size: 12px; color: #7a8a7e; }
.reason { font-size: 13px; margin: 4px 0; }
.draft {
  font-size: 11px;
  background: #f8faf8;
  border: 1px solid #e8eee8;
  border-radius: 6px;
  padding: 8px;
  max-height: 180px;
  overflow: auto;
  margin: 4px 0 0;
}
.shadow { display: flex; gap: 14px; font-size: 13px; margin-top: 4px; }
.shadow .added { color: #16a34a; }
.shadow .removed { color: #dc2626; }
.ops { margin-top: 10px; display: flex; gap: 8px; align-items: center; }
.rev-card.rejected { opacity: 0.65; }
</style>
