<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { fieldsApi } from '../api'
import type { Field } from '../types'

const list = ref<Field[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    list.value = await fieldsApi.list()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
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
  Object.assign(form, { name: '', boundary: '', area_ha: null, soil_type: '', notes: '' })
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
    ElMessage.error(e instanceof Error ? e.message : String(e))
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
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

function vertices(row: Field): number {
  return row.boundary?.coordinates?.[0]?.length ?? 0
}
</script>

<template>
  <div class="toolbar">
    <el-button type="primary" :icon="Plus" @click="openCreate">新增地块</el-button>
    <el-button :icon="Refresh" circle title="刷新" @click="load" />
  </div>

  <el-table :data="list" v-loading="loading" border stripe>
    <el-table-column prop="id" label="ID" width="64" />
    <el-table-column prop="name" label="名称" min-width="140" />
    <el-table-column label="边界" width="130">
      <template #default="{ row }">
        <el-tag type="success" effect="plain">多边形 · {{ vertices(row) }} 顶点</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="面积(公顷)" width="110">
      <template #default="{ row }">{{ row.area_ha ?? '—' }}</template>
    </el-table-column>
    <el-table-column label="土壤" width="100">
      <template #default="{ row }">{{ row.soil_type ?? '—' }}</template>
    </el-table-column>
    <el-table-column prop="notes" label="备注" min-width="140" show-overflow-tooltip />
    <el-table-column label="操作" width="150" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="openEdit(row)">编辑</el-button>
        <el-button size="small" type="danger" plain @click="removeRow(row)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>

  <el-dialog
    v-model="dialogVisible"
    :title="editingId == null ? '新增地块' : `编辑地块 #${editingId}`"
    width="560px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="如：北坡一号地" maxlength="100" />
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
.toolbar {
  margin-bottom: 14px;
  display: flex;
  gap: 10px;
}
</style>
