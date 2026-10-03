<script setup lang="ts">
/** 株档案（计划 0014）：一块地的每株档案、批量建档、设施类型；上传时自动建的档案可筛出来核对。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Plus, Refresh } from '@element-plus/icons-vue'
import { fieldsApi, observationUnitsApi, type UnitBulkRow } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { FacilityType, Field, ObservationUnit, UnitSource, UnitStatus } from '../types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const fieldId = Number(route.params.id)

const FACILITY_LABELS: Record<FacilityType, string> = {
  open_field: '大田',
  solar_greenhouse: '日光温室',
  plastic_tunnel: '塑料大棚',
}
const SOURCE_LABELS: Record<UnitSource, string> = { manual: '手工', bulk: '批量', ingest: '上传自动建' }
const STATUS_LABELS: Record<UnitStatus, string> = { active: '在册', retired: '停用' }

const field = ref<Field | null>(null)
const units = ref<ObservationUnit[]>([])
const loading = ref(false)
const filters = reactive({ row_no: undefined as number | undefined, status: '' as UnitStatus | '', created_from: '' as UnitSource | '' })

async function load() {
  loading.value = true
  try {
    const [f, list] = await Promise.all([
      fieldsApi.get(fieldId),
      observationUnitsApi.list(fieldId, {
        row_no: filters.row_no || undefined,
        status: filters.status || undefined,
        created_from: filters.created_from || undefined,
      }),
    ])
    field.value = f
    units.value = list
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  if (!Number.isInteger(fieldId) || fieldId <= 0) {
    void router.replace({ name: 'fields' })
    return
  }
  void load()
})

const rowCount = computed(() => new Set(units.value.map((u) => u.row_no).filter((r) => r != null)).size)
const pendingReview = computed(() => units.value.filter((u) => u.created_from === 'ingest').length)

/* ---------- 设施类型 ---------- */
async function saveFacility(value: FacilityType | null) {
  try {
    field.value = await fieldsApi.update(fieldId, { facility_type: value })
    ElMessage.success('设施类型已更新')
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
    const result = await observationUnitsApi.bulk(fieldId, bulkRows.value)
    ElMessage.success(`新建 ${result.created} 株，已存在跳过 ${result.skipped} 株`)
    bulkVisible.value = false
    await load()
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
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

/* ---------- 单株新建 ---------- */
const createVisible = ref(false)
const creating = reactive({ key: '', tag_code: '', chainage_m: null as number | null })
async function submitCreate() {
  try {
    await observationUnitsApi.create(fieldId, {
      key: creating.key.trim(),
      tag_code: creating.tag_code.trim() || null,
      chainage_m: creating.chainage_m,
    })
    ElMessage.success('已建档')
    createVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
</script>

<template>
  <div class="head">
    <el-button :icon="ArrowLeft" text @click="router.push({ name: 'fields' })">地块管理</el-button>
    <span class="title">{{ field?.name ?? `地块 #${fieldId}` }} · 株档案</span>
    <span class="facility">
      设施类型
      <el-select
        :model-value="field?.facility_type ?? null"
        :disabled="auth.isViewer"
        placeholder="大田（未设置）"
        clearable
        size="small"
        style="width: 140px"
        @change="saveFacility"
      >
        <el-option v-for="(label, value) in FACILITY_LABELS" :key="value" :label="label" :value="value" />
      </el-select>
    </span>
  </div>

  <div class="toolbar">
    <el-input-number v-model="filters.row_no" :min="1" :max="99" placeholder="垄号" controls-position="right" size="default" style="width: 110px" />
    <el-select v-model="filters.status" placeholder="状态" clearable style="width: 100px">
      <el-option v-for="(label, value) in STATUS_LABELS" :key="value" :label="label" :value="value" />
    </el-select>
    <el-select v-model="filters.created_from" placeholder="来源" clearable style="width: 130px">
      <el-option v-for="(label, value) in SOURCE_LABELS" :key="value" :label="label" :value="value" />
    </el-select>
    <el-button @click="load">筛选</el-button>
    <el-button :icon="Refresh" circle title="刷新" @click="load" />
    <span class="spacer" />
    <template v-if="!auth.isViewer">
      <el-button :icon="Plus" @click="createVisible = true">单株建档</el-button>
      <el-button type="primary" :icon="Plus" @click="openBulk">批量建档</el-button>
    </template>
  </div>

  <div class="summary">
    共 {{ units.length }} 株 · {{ rowCount }} 垄
    <el-tag v-if="pendingReview" type="warning" effect="plain" size="small">{{ pendingReview }} 株为上传时自动建档，待核对</el-tag>
  </div>

  <el-table :data="units" v-loading="loading" border stripe size="small">
    <el-table-column prop="key" label="株号" width="130">
      <template #default="{ row }">
        <el-link type="primary" @click="router.push({ name: 'unit-timeline', params: { id: row.id } })">{{ row.key }}</el-link>
      </template>
    </el-table-column>
    <el-table-column label="垄号" width="70">
      <template #default="{ row }">{{ row.row_no ?? '—' }}</template>
    </el-table-column>
    <el-table-column label="株序号" width="80">
      <template #default="{ row }">{{ row.position_no ?? '—' }}</template>
    </el-table-column>
    <el-table-column label="行内位置(m)" width="110">
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
        <el-button v-if="!auth.isViewer" size="small" @click="openEdit(row)">编辑</el-button>
      </template>
    </el-table-column>
  </el-table>

  <el-dialog v-model="bulkVisible" title="批量建档" width="640px">
    <p class="hint">按推荐格式生成株号 R{垄号两位}-P{株序号三位}，如 R03-P017；已有的株号会跳过，可重复提交。</p>
    <el-table :data="bulkRows" size="small" border>
      <el-table-column label="垄号" width="110">
        <template #default="{ row }"><el-input-number v-model="row.row_no" :min="1" :max="99" size="small" controls-position="right" /></template>
      </el-table-column>
      <el-table-column label="株数" width="120">
        <template #default="{ row }"><el-input-number v-model="row.plants" :min="1" :max="999" size="small" controls-position="right" /></template>
      </el-table-column>
      <el-table-column label="株距(m)" width="120">
        <template #default="{ row }"><el-input-number v-model="row.spacing_m" :min="0.05" :max="10" :step="0.05" :precision="2" size="small" controls-position="right" /></template>
      </el-table-column>
      <el-table-column label="首株位置(m)" width="130">
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
    <el-form label-width="90px">
      <el-form-item label="株号"><el-input v-model="creating.key" placeholder="R03-P017 或自定义编号" maxlength="80" /></el-form-item>
      <el-form-item label="标签"><el-input v-model="creating.tag_code" placeholder="二维码内容（可空）" maxlength="80" /></el-form-item>
      <el-form-item label="行内位置(m)"><el-input-number v-model="creating.chainage_m" :min="0" :step="0.1" :precision="2" /></el-form-item>
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
.head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; }
.facility { margin-left: auto; display: flex; align-items: center; gap: 8px; color: var(--el-text-color-regular); font-size: 13px; }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
.spacer { flex: 1; }
.summary { margin-bottom: 8px; font-size: 13px; color: var(--el-text-color-secondary); display: flex; gap: 10px; align-items: center; }
.hint { margin: 0 0 10px; font-size: 13px; color: var(--el-text-color-secondary); }
</style>
