<script setup lang="ts">
/**
 * 盲法复核（计划 0007 P1-9，D25）：建批次、看进度、看结果。判读在 BlindReviewSessionView 里做，只给照片。
 * 批次 = 一个棚、一段田间日期里按种子随机抽的合格照片 + 固定参考株的全部合格照片，打乱顺序。
 * 逐张结果（带株号、拍摄时间）要等全部定论后才给，判读中途只看汇总。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { blindReviewApi, fieldsApi } from '../api'
import { errMsg } from '../api/http'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { BLIND_OPTIONS, type BlindReviewBatch, type BlindReviewResult, type Field } from '../types'
import { fieldClock, fieldDate } from '../utils/fieldTime'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()
const fields = ref<Field[]>([])
const fieldId = ref<number | null>(ui.currentFieldId)
const batches = ref<BlindReviewBatch[]>([])
const loading = ref(false)

const LABEL_TEXT: Record<string, string> = Object.fromEntries(BLIND_OPTIONS.map((o) => [o.label, o.text]))
const ORIGIN_TEXT: Record<string, string> = { random: '随机抽查', reference: '固定参考' }
const HOW_TEXT: Record<string, string> = { agreed: '两人一致', adjudicated: '二次判读' }

async function load() {
  loading.value = true
  try {
    if (!fields.value.length) fields.value = await fieldsApi.list()
    if (fieldId.value == null && fields.value.length) fieldId.value = fields.value[0].id
    batches.value = fieldId.value == null ? [] : await blindReviewApi.list(fieldId.value)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
watch(fieldId, () => { void load() })
onMounted(load)

const percent = (value: number | null) => (value == null ? '—' : `${Math.round(value * 100)}%`)
const kappa = (value: number | null) => (value == null ? '—' : value.toFixed(2))
function progress(row: BlindReviewBatch) {
  return row.item_count ? Math.round((row.summary.resolved / row.item_count) * 100) : 0
}

/* ---------- 新建批次 ---------- */
const dialogVisible = ref(false)
const submitting = ref(false)
const form = reactive({
  name: '',
  range: [] as string[],
  sample_size: 40,
  reference: '',
  under_only: true,
  double_review: true,
  seed: 0,
})
function openCreate() {
  const today = fieldDate()
  form.name = `${today} 盲评`
  form.range = [today, today]
  dialogVisible.value = true
}
async function submitCreate() {
  if (fieldId.value == null) return
  if (!form.name.trim() || form.range.length !== 2) {
    ElMessage.warning('请填写名称和日期范围')
    return
  }
  submitting.value = true
  try {
    const batch = await blindReviewApi.create({
      field_id: fieldId.value, name: form.name.trim(), date_from: form.range[0], date_to: form.range[1],
      sample_size: form.sample_size, seed: form.seed,
      reference_keys: form.reference.split(/[\s,，、]+/).map((k) => k.trim()).filter(Boolean),
      side: form.under_only ? 'under' : 'any', double_review: form.double_review,
    })
    ElMessage.success(`已建批次，共 ${batch.item_count} 张`)
    dialogVisible.value = false
    await load()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { submitting.value = false }
}

/* ---------- 结果 ---------- */
const resultBatch = ref<BlindReviewBatch | null>(null)
const results = ref<BlindReviewResult[]>([])
const resultsVisible = computed({
  get: () => resultBatch.value != null,
  set: (open: boolean) => { if (!open) resultBatch.value = null },
})
async function openResults(row: BlindReviewBatch) {
  try {
    results.value = await blindReviewApi.results(row.id)
    resultBatch.value = row
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function distribution(origin: string): string {
  const counts = resultBatch.value?.summary.final_labels[origin] ?? {}
  const parts = BLIND_OPTIONS.filter((o) => counts[o.label]).map((o) => `${o.text} ${counts[o.label]}`)
  return parts.length ? parts.join('、') : '—'
}
</script>

<template>
  <PageHeader title="盲法复核" subtitle="独立测试集的标签在看不到模型输出时判读：两人独立判读，分歧由第三人二次判读；随机抽查覆盖低风险株">
    <template #actions>
      <el-select v-model="fieldId" placeholder="选择地块" class="f-field">
        <el-option v-for="f in fields" :key="f.id" :label="f.name" :value="f.id" />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      <el-button v-if="!auth.isViewer" type="primary" :icon="Plus" :disabled="fieldId == null" @click="openCreate">新建批次</el-button>
    </template>
  </PageHeader>

  <SectionCard flush>
    <el-table :data="batches" v-loading="loading">
      <el-table-column label="批次" min-width="150">
        <template #default="{ row }">{{ row.name }} <span class="muted text-12">#{{ row.id }}</span></template>
      </el-table-column>
      <el-table-column label="照片日期" width="170">
        <template #default="{ row }"><span class="nowrap">{{ row.params.date_from.slice(5) }} 至 {{ row.params.date_to.slice(5) }}</span> <span class="muted text-12">{{ row.params.date_from.slice(0, 4) }}</span></template>
      </el-table-column>
      <el-table-column label="张数" min-width="200">
        <template #default="{ row }">
          {{ row.item_count }}
          <span class="muted text-12">随机 {{ row.params.sample_size }} · 参考株 {{ row.params.reference_keys.length }} · {{ row.params.double_review ? '两人判读' : '单人判读' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="已定论" width="170">
        <template #default="{ row }">
          <div class="progress">
            <el-progress :percentage="progress(row)" :show-text="false" :stroke-width="6" />
            <span class="text-12">{{ row.summary.resolved }} / {{ row.item_count }}</span>
          </div>
          <span v-if="row.summary.status_counts.disputed" class="text-12 warn">待二次判读 {{ row.summary.status_counts.disputed }}</span>
        </template>
      </el-table-column>
      <el-table-column label="两人一致率 · κ" width="140">
        <template #default="{ row }">
          <template v-if="row.summary.pairs">{{ percent(row.summary.agreement) }} · {{ kappa(row.summary.kappa) }}</template>
          <span v-else class="muted text-12">{{ row.params.double_review ? '尚无成对判读' : '单人判读' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="我已判读" width="90" align="right">
        <template #default="{ row }">{{ row.summary.my_votes ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="row.status === 'done' ? 'success' : 'warning'">{{ row.status === 'done' ? '已完成' : '判读中' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'open' && !auth.isViewer" size="small" type="primary" plain
                     @click="router.push(`/blind-review/${row.id}`)">去判读</el-button>
          <el-button v-if="row.status === 'done'" size="small" text type="primary" @click="openResults(row)">结果</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState compact title="还没有盲评批次" description="新建批次后，判读人在「去判读」里逐张看照片；全部定论后才能看逐张结果" />
      </template>
    </el-table>
  </SectionCard>

  <el-dialog v-model="dialogVisible" title="新建盲评批次" width="560px">
    <el-form label-width="120px">
      <el-form-item label="名称"><el-input v-model="form.name" maxlength="100" /></el-form-item>
      <el-form-item label="照片日期">
        <el-date-picker v-model="form.range" type="daterange" value-format="YYYY-MM-DD" range-separator="至"
                        start-placeholder="开始" end-placeholder="结束" />
      </el-form-item>
      <el-form-item label="随机抽样张数">
        <el-input-number v-model="form.sample_size" :min="0" :max="500" />
        <span class="muted text-12 hint">不看风险高低，按种子随机抽，用来估计漏报</span>
      </el-form-item>
      <el-form-item label="固定参考株">
        <el-input v-model="form.reference" placeholder="如 R01-P005, R02-P010；这些株在范围内的合格照片全部入批" />
      </el-form-item>
      <el-form-item label="只收合格叶背"><el-switch v-model="form.under_only" /></el-form-item>
      <el-form-item label="两人独立判读">
        <el-switch v-model="form.double_review" />
        <span class="muted text-12 hint">不一致时由第三人二次判读</span>
      </el-form-item>
      <el-form-item label="种子"><el-input-number v-model="form.seed" :min="0" :max="2147483647" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submitCreate">建批次</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="resultsVisible" :title="resultBatch ? `${resultBatch.name} · 结果` : ''" width="760px">
    <template v-if="resultBatch">
      <p class="text-13">
        已定论 {{ resultBatch.summary.resolved }} / {{ resultBatch.item_count }} 张；<template v-if="resultBatch.summary.pairs">两人一致率 {{ percent(resultBatch.summary.agreement) }}，κ {{ kappa(resultBatch.summary.kappa) }}，二次判读 {{ resultBatch.summary.status_counts.adjudicated }} 张。</template>
        <template v-else>单人判读，没有一致率。</template>
      </p>
      <p class="text-13">随机抽查：{{ distribution('random') }}；固定参考：{{ distribution('reference') }}</p>
      <el-table :data="results" max-height="420">
        <el-table-column prop="position" label="序号" width="64" />
        <el-table-column label="株号" width="110"><template #default="{ row }">{{ row.observation_key ?? '—' }}</template></el-table-column>
        <el-table-column label="拍摄时间" width="140"><template #default="{ row }">{{ fieldClock(row.captured_at) }}</template></el-table-column>
        <el-table-column label="来源" width="90"><template #default="{ row }">{{ ORIGIN_TEXT[row.origin] ?? row.origin }}</template></el-table-column>
        <el-table-column label="怎么定的" width="100"><template #default="{ row }">{{ HOW_TEXT[row.status] ?? row.status }}</template></el-table-column>
        <el-table-column label="结论" min-width="80"><template #default="{ row }">{{ LABEL_TEXT[row.final_label] ?? row.final_label }}</template></el-table-column>
      </el-table>
    </template>
  </el-dialog>
</template>

<style scoped>
.f-field { width: 180px; }
.progress { display: flex; align-items: center; gap: var(--space-2); }
.progress .el-progress { flex: 1; }
.warn { color: var(--warning-ink); }
.hint { margin-left: var(--space-2); }
.nowrap { white-space: nowrap; }
</style>
