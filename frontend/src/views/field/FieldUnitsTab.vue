<script setup lang="ts">
/** 大棚详情 · 株档案（0014 的株档案页挪进来）：每株档案、批量建档、设施类型；上传时自动建的档案可筛出来核对。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Files, Plus } from '@element-plus/icons-vue'
import EmptyState from '../../components/ui/EmptyState.vue'
import SectionCard from '../../components/ui/SectionCard.vue'
import { fieldsApi, observationUnitsApi, type UnitBulkRow } from '../../api'
import { errMsg } from '../../api/http'
import { useFieldDetail } from '../../composables/useFieldDetail'
import { useAuthStore } from '../../stores/auth'
import { useFieldsStore } from '../../stores/fields'
import { FACILITY_LABELS, type FacilityType, type ObservationUnit, type UnitSource, type UnitStatus } from '../../types'

const d = useFieldDetail()
const router = useRouter()
const auth = useAuthStore()
const fieldsStore = useFieldsStore()

const SOURCE_LABELS: Record<UnitSource, string> = { manual: '手工', bulk: '批量', ingest: '上传自动建' }
const STATUS_LABELS: Record<UnitStatus, string> = { active: '在册', retired: '停用' }

const units = ref<ObservationUnit[]>([])
const loading = ref(false)
const filters = reactive({ row_no: undefined as number | undefined, status: '' as UnitStatus | '', created_from: '' as UnitSource | '' })

async function load() {
  loading.value = true
  try {
    units.value = await observationUnitsApi.list(d.fieldId, {
      row_no: filters.row_no || undefined,
      status: filters.status || undefined,
      created_from: filters.created_from || undefined,
    })
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

const rowCount = computed(() => new Set(units.value.map((u) => u.row_no).filter((r) => r != null)).size)
const pendingReview = computed(() => units.value.filter((u) => u.created_from === 'ingest').length)
const filtered = computed(() => !!(filters.row_no || filters.status || filters.created_from))

/** 档案变了：概览的网格、页头计数跟着重拉 */
function changed() {
  void d.states.load(true)
  return load()
}

/* ---------- 设施类型 ---------- */
async function saveFacility(value: FacilityType | null) {
  try {
    d.field.data.value = await fieldsApi.update(d.fieldId, { facility_type: value })
    ElMessage.success('设施类型已更新')
    void fieldsStore.load(true).catch(() => { /* 只影响顶栏切换器的分组 */ })
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

/* ---------- 批量建档 ---------- */
const bulkVisible = ref(false)
const bulkSubmitting = ref(false)
const bulkRows = ref<UnitBulkRow[]>([])
function openBulk() {
  bulkRows.value = [{ row_no: 1, plants: 30, spacing_m: 0.4, start_chainage_m: 0 }]
  bulkVisible.value = true
}
function addBulkRow() {
  const last = bulkRows.value[bulkRows.value.length - 1]
  bulkRows.value.push({ ...(last ?? { plants: 30, spacing_m: 0.4, start_chainage_m: 0 }), row_no: (last?.row_no ?? 0) + 1 })
}
async function submitBulk() {
  bulkSubmitting.value = true
  try {
    const result = await observationUnitsApi.bulk(d.fieldId, bulkRows.value)
    ElMessage.success(`新建 ${result.created} 株，已存在跳过 ${result.skipped} 株`)
    bulkVisible.value = false
    await changed()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    bulkSubmitting.value = false
  }
}

/* ---------- 单株编辑 ---------- */
const editVisible = ref(false)
const editing = reactive({ id: 0, key: '', tag_code: '', status: 'active' as UnitStatus, note: '' })
function openEdit(row: ObservationUnit) {
  Object.assign(editing, { id: row.id, key: row.key, tag_code: row.tag_code ?? '', status: row.status, note: row.note ?? '' })
  editVisible.value = true
}
async function submitEdit() {
  try {
    await observationUnitsApi.update(editing.id, {
      tag_code: editing.tag_code.trim() || null,
      status: editing.status,
      note: editing.note.trim() || null,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    await changed()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

/* ---------- 单株新建 ---------- */
const createVisible = ref(false)
const creating = reactive({ key: '', tag_code: '', chainage_m: null as number | null })
async function submitCreate() {
  try {
    await observationUnitsApi.create(d.fieldId, {
      key: creating.key.trim(),
      tag_code: creating.tag_code.trim() || null,
      chainage_m: creating.chainage_m,
    })
    ElMessage.success('已建档')
    createVisible.value = false
    await changed()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
</script>

<template>
  <div class="toolbar">
    <el-input-number v-model="filters.row_no" :min="1" :max="99" placeholder="垄号" controls-position="right" style="width: 110px" />
    <el-select v-model="filters.status" placeholder="状态" clearable style="width: 100px">
      <el-option v-for="(label, value) in STATUS_LABELS" :key="value" :label="label" :value="value" />
    </el-select>
    <el-select v-model="filters.created_from" placeholder="来源" clearable style="width: 130px">
      <el-option v-for="(label, value) in SOURCE_LABELS" :key="value" :label="label" :value="value" />
    </el-select>
    <el-button @click="load">筛选</el-button>
    <span class="spacer" />
    <span class="facility">
      设施类型
      <el-select :model-value="d.field.data.value?.facility_type ?? null" :disabled="auth.isViewer" placeholder="大田（未设置）"
                 clearable style="width: 130px" @change="saveFacility">
        <el-option v-for="(label, value) in FACILITY_LABELS" :key="value" :label="label" :value="value" />
      </el-select>
    </span>
    <template v-if="!auth.isViewer">
      <el-button :icon="Plus" @click="createVisible = true">单株建档</el-button>
      <el-button type="primary" :icon="Plus" @click="openBulk">批量建档</el-button>
    </template>
  </div>

  <SectionCard flush>
    <template #title>
      <div class="summary">
        <h2>共 {{ units.length }} 株 · {{ rowCount }} 垄<span v-if="filtered" class="muted">（已筛选）</span></h2>
        <el-tag v-if="pendingReview" type="warning" effect="plain" size="small">{{ pendingReview }} 株为上传时自动建档，待核对</el-tag>
      </div>
    </template>
    <el-table :data="units" v-loading="loading" size="small" stripe>
      <el-table-column prop="key" label="株号" width="130">
        <template #default="{ row }">
          <router-link :to="{ name: 'unit-timeline', params: { id: row.id } }" class="mono">{{ row.key }}</router-link>
        </template>
      </el-table-column>
      <el-table-column label="垄号" width="70" align="right">
        <template #default="{ row }">{{ row.row_no ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="株序号" width="80" align="right">
        <template #default="{ row }">{{ row.position_no ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="行内位置（米）" width="120" align="right">
        <template #default="{ row }">{{ row.chainage_m ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="标签" width="120">
        <template #default="{ row }">{{ row.tag_code ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain" size="small">{{ STATUS_LABELS[row.status as UnitStatus] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="110">
        <template #default="{ row }">
          <el-tag :type="row.created_from === 'ingest' ? 'warning' : 'info'" effect="plain" size="small">
            {{ SOURCE_LABELS[row.created_from as UnitSource] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="router.push({ name: 'unit-timeline', params: { id: row.id } })">时间线</el-button>
          <el-button v-if="!auth.isViewer" size="small" text @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState :icon="Files" :title="filtered ? '没有符合条件的株' : '还没有株档案'"
                    :description="filtered ? '' : auth.isViewer ? '由操作员或管理员建档。' : '点右上角「批量建档」按垄生成株号。'" />
      </template>
    </el-table>
  </SectionCard>

  <el-dialog v-model="bulkVisible" title="批量建档" width="640px">
    <p class="hint">按推荐格式生成株号 R{垄号两位}-P{株序号三位}，如 R03-P017；已有的株号会跳过，可重复提交。</p>
    <el-table :data="bulkRows" size="small" border>
      <el-table-column label="垄号" width="110">
        <template #default="{ row }"><el-input-number v-model="row.row_no" :min="1" :max="99" size="small" controls-position="right" /></template>
      </el-table-column>
      <el-table-column label="株数" width="120">
        <template #default="{ row }"><el-input-number v-model="row.plants" :min="1" :max="999" size="small" controls-position="right" /></template>
      </el-table-column>
      <el-table-column label="株距（米）" width="120">
        <template #default="{ row }"><el-input-number v-model="row.spacing_m" :min="0.05" :max="10" :step="0.05" :precision="2" size="small" controls-position="right" /></template>
      </el-table-column>
      <el-table-column label="首株位置（米）" width="130">
        <template #default="{ row }"><el-input-number v-model="row.start_chainage_m" :min="0" :step="0.5" :precision="2" size="small" controls-position="right" /></template>
      </el-table-column>
      <el-table-column label="" width="70">
        <template #default="{ $index }">
          <el-button size="small" text type="danger" :disabled="bulkRows.length === 1" @click="bulkRows.splice($index, 1)">移除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button size="small" text type="primary" :icon="Plus" @click="addBulkRow">再加一垄</el-button>
    <template #footer>
      <el-button @click="bulkVisible = false">取消</el-button>
      <el-button type="primary" :loading="bulkSubmitting" @click="submitBulk">建档</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="createVisible" title="单株建档" width="440px">
    <el-form label-width="100px">
      <el-form-item label="株号"><el-input v-model="creating.key" placeholder="R03-P017 或自定义编号" maxlength="80" /></el-form-item>
      <el-form-item label="标签"><el-input v-model="creating.tag_code" placeholder="二维码内容（可空）" maxlength="80" /></el-form-item>
      <el-form-item label="行内位置（米）"><el-input-number v-model="creating.chainage_m" :min="0" :step="0.1" :precision="2" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createVisible = false">取消</el-button>
      <el-button type="primary" :disabled="!creating.key.trim()" @click="submitCreate">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="editVisible" :title="`编辑 ${editing.key}`" width="440px">
    <el-form label-width="70px">
      <el-form-item label="标签"><el-input v-model="editing.tag_code" maxlength="80" /></el-form-item>
      <el-form-item label="状态">
        <el-radio-group v-model="editing.status">
          <el-radio-button v-for="(label, value) in STATUS_LABELS" :key="value" :value="value">{{ label }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="editing.note" type="textarea" :rows="2" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editVisible = false">取消</el-button>
      <el-button type="primary" @click="submitEdit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; margin-bottom: var(--space-4); }
.toolbar :deep(.el-button + .el-button) { margin-left: 0; }
.spacer { flex: 1; }
.facility { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--fs-13); color: var(--text-secondary); }
.summary { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-3); }
.summary h2 { margin: 0; font-size: var(--fs-16); line-height: var(--lh-16); font-weight: var(--fw-semibold); }
.summary h2 .muted { font-size: var(--fs-13); font-weight: var(--fw-regular); }
.mono { font-family: var(--font-mono); font-size: var(--fs-13); }
.hint { margin: 0 0 var(--space-3); font-size: var(--fs-13); color: var(--text-secondary); }
</style>
