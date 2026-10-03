<script setup lang="ts">
/** 大棚与地块（计划 0018 套新外壳）：列表与增删改；大棚行可进巡检计划和株档案。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { MapLocation, Plus, Refresh } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import { fieldsApi } from '../api'
import { errMsg } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { useFieldsStore } from '../stores/fields'
import { FACILITY_LABELS, isGreenhouse, type FacilityType, type Field } from '../types'

const router = useRouter()
const auth = useAuthStore()
const fieldsStore = useFieldsStore()

// 与顶栏地块切换器共用一份列表，增删改后两边一起刷新
const list = computed(() => fieldsStore.list)
const greenhouseCount = computed(() => list.value.filter((f) => isGreenhouse(f)).length)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    await fieldsStore.load(true)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

/* ---------- 表单弹窗 ---------- */
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()

const BOUNDARY_TEMPLATE = JSON.stringify(
  {
    type: 'Polygon',
    coordinates: [
      [[116.1, 39.1], [116.12, 39.1], [116.12, 39.12], [116.1, 39.12], [116.1, 39.1]],
    ],
  },
  null,
  2,
)

const form = reactive({
  name: '',
  boundary: '',
  area_ha: null as number | null,
  soil_type: '',
  notes: '',
  facility_type: 'open_field' as FacilityType,
})

function validateBoundary(_rule: unknown, value: string, callback: (err?: Error) => void) {
  if (!value.trim()) return callback(new Error('请输入 GeoJSON 边界'))
  try {
    const obj = JSON.parse(value)
    if (obj?.type !== 'Polygon' || !Array.isArray(obj.coordinates)) {
      return callback(new Error('需为 {"type":"Polygon","coordinates":[…]} 结构'))
    }
    callback()
  } catch {
    callback(new Error('JSON 解析失败'))
  }
}

const rules: FormRules = {
  name: [{ required: true, message: '请输入地块名称', trigger: 'blur' }],
  boundary: [{ required: true, validator: validateBoundary, trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', boundary: '', area_ha: null, soil_type: '', notes: '', facility_type: 'solar_greenhouse' })
  dialogVisible.value = true
}

function openEdit(row: Field) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    boundary: JSON.stringify(row.boundary, null, 2),
    area_ha: row.area_ha,
    soil_type: row.soil_type ?? '',
    notes: row.notes ?? '',
    facility_type: row.facility_type ?? 'open_field',
  })
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  const payload = {
    name: form.name.trim(),
    boundary: JSON.parse(form.boundary),
    area_ha: form.area_ha,
    soil_type: form.soil_type || null,
    notes: form.notes || null,
    facility_type: form.facility_type,
  }
  try {
    if (editingId.value == null) {
      await fieldsApi.create(payload)
      ElMessage.success('地块已创建')
    } else {
      await fieldsApi.update(editingId.value, payload)
      ElMessage.success('地块已更新')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    submitting.value = false
  }
}

async function removeRow(row: Field) {
  try {
    await ElMessageBox.confirm(`确认删除地块「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await fieldsApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

function vertices(row: Field): number {
  return row.boundary?.coordinates?.[0]?.length ?? 0
}
</script>

<template>
  <PageHeader title="大棚与地块" subtitle="日光温室、塑料大棚按株巡检；大田为小麦方法验证资产（D16 保留）">
    <template #meta>
      <span class="count-chip">大棚 <b>{{ greenhouseCount }}</b></span>
      <span class="count-chip">大田 <b>{{ list.length - greenhouseCount }}</b></span>
    </template>
    <template #actions>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      <el-button v-if="!auth.isViewer" type="primary" :icon="Plus" @click="openCreate">新增地块</el-button>
    </template>
  </PageHeader>

  <SectionCard flush>
    <el-table :data="list" v-loading="loading" row-key="id">
      <el-table-column label="名称" min-width="200">
        <template #default="{ row }">
          <div class="name-cell">
            <b>{{ row.name }}</b>
            <span class="muted text-12">#{{ row.id }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="设施" width="120">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="isGreenhouse(row) ? 'primary' : 'info'">
            {{ FACILITY_LABELS[(row.facility_type ?? 'open_field') as FacilityType] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="面积（公顷）" width="120" align="right">
        <template #default="{ row }"><span class="tabular">{{ row.area_ha ?? '—' }}</span></template>
      </el-table-column>
      <el-table-column label="土壤" width="100">
        <template #default="{ row }">{{ row.soil_type ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="边界" width="120">
        <template #default="{ row }"><span class="muted">多边形 · {{ vertices(row) }} 点</span></template>
      </el-table-column>
      <el-table-column prop="notes" label="备注" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.notes || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <div class="ops">
            <el-button v-if="isGreenhouse(row)" size="small" type="primary" plain
                       @click="router.push({ name: 'field-plan', params: { id: row.id } })">巡检计划</el-button>
            <el-button size="small" @click="router.push({ name: 'field-units', params: { id: row.id } })">株档案</el-button>
            <template v-if="!auth.isViewer">
              <el-button size="small" text @click="openEdit(row)">编辑</el-button>
              <el-button size="small" text type="danger" @click="removeRow(row)">删除</el-button>
            </template>
          </div>
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState :icon="MapLocation" title="还没有地块" description="新增地块时设施类型选日光温室或塑料大棚，就能建株档案、生成巡检计划。" />
      </template>
    </el-table>
  </SectionCard>

  <el-dialog
    v-model="dialogVisible"
    :title="editingId == null ? '新增地块' : `编辑地块 #${editingId}`"
    width="560px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="如：1号日光温室（黄瓜）" maxlength="100" />
      </el-form-item>
      <el-form-item label="设施类型">
        <el-radio-group v-model="form.facility_type">
          <el-radio-button v-for="(label, value) in FACILITY_LABELS" :key="value" :value="value">{{ label }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="GeoJSON" prop="boundary">
        <el-input
          v-model="form.boundary"
          type="textarea"
          :rows="6"
          placeholder='粘贴 GeoJSON Polygon；地图画边界将在 M6 提供'
        />
        <el-button size="small" text type="primary" @click="form.boundary = BOUNDARY_TEMPLATE">
          填入示例模板
        </el-button>
      </el-form-item>
      <el-form-item label="面积(公顷)">
        <el-input-number v-model="form.area_ha" :min="0" :precision="2" :step="0.5" />
      </el-form-item>
      <el-form-item label="土壤类型">
        <el-input v-model="form.soil_type" placeholder="壤土 / 砂土 / 黏土…" maxlength="50" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.notes" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.count-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 24px;
  padding: 0 var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  font-size: var(--fs-12);
  color: var(--text-secondary);
}
.count-chip b { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.name-cell { display: flex; align-items: baseline; gap: var(--space-2); }
.name-cell b { font-weight: var(--fw-medium); color: var(--text-primary); }
.ops { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.ops :deep(.el-button + .el-button) { margin-left: 0; }
</style>
