<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { cropsApi, fieldsApi, plantingsApi } from '../api'
import { PLANTING_STATUS_LABELS, type Crop, type Field, type Planting, type PlantingStatus } from '../types'

const list = ref<Planting[]>([])
const fields = ref<Field[]>([])
const crops = ref<Crop[]>([])
const loading = ref(false)
const filterFieldId = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    list.value = await plantingsApi.list({ field_id: filterFieldId.value ?? undefined })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

async function loadReferences() {
  try {
    ;[fields.value, crops.value] = await Promise.all([fieldsApi.list(), cropsApi.list()])
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

onMounted(() => {
  void load()
  void loadReferences()
})

const fieldById = computed(() => new Map(fields.value.map((f) => [f.id, f])))
const cropById = computed(() => new Map(crops.value.map((c) => [c.id, c])))

/* ---------- 表单弹窗 ---------- */
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  field_id: null as number | null,
  crop_id: null as number | null,
  sowing_date: '',
  expected_harvest_date: '' as string | null,
  status: 'active' as PlantingStatus,
  notes: '',
})

const rules: FormRules = {
  field_id: [{ required: true, message: '请选择地块', trigger: 'change' }],
  crop_id: [{ required: true, message: '请选择作物', trigger: 'change' }],
  sowing_date: [{ required: true, message: '请选择播种日期', trigger: 'change' }],
}

/** 选定作物+播种日期后，按生命周期天数自动推算预计收获日 */
function autoFillHarvest() {
  const crop = form.crop_id != null ? cropById.value.get(form.crop_id) : undefined
  if (!crop || !form.sowing_date) return
  const sow = new Date(form.sowing_date)
  sow.setDate(sow.getDate() + crop.lifecycle_days)
  form.expected_harvest_date = sow.toISOString().slice(0, 10)
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    field_id: filterFieldId.value,
    crop_id: null,
    sowing_date: '',
    expected_harvest_date: null,
    status: 'active',
    notes: '',
  })
  dialogVisible.value = true
}

function openEdit(row: Planting) {
  editingId.value = row.id
  Object.assign(form, {
    field_id: row.field_id,
    crop_id: row.crop_id,
    sowing_date: row.sowing_date,
    expected_harvest_date: row.expected_harvest_date,
    status: row.status,
    notes: row.notes ?? '',
  })
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (editingId.value == null) {
      await plantingsApi.create({
        field_id: form.field_id!,
        crop_id: form.crop_id!,
        sowing_date: form.sowing_date,
        expected_harvest_date: form.expected_harvest_date || null,
        status: form.status,
        notes: form.notes || null,
      })
      ElMessage.success('种植记录已创建')
    } else {
      await plantingsApi.update(editingId.value, {
        sowing_date: form.sowing_date,
        expected_harvest_date: form.expected_harvest_date || null,
        status: form.status,
        notes: form.notes || null,
      })
      ElMessage.success('种植记录已更新')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    submitting.value = false
  }
}

async function removeRow(row: Planting) {
  const fname = row.field_name ?? fieldById.value.get(row.field_id)?.name ?? row.field_id
  const cname = row.crop_name ?? cropById.value.get(row.crop_id)?.name ?? row.crop_id
  try {
    await ElMessageBox.confirm(`确认删除「${fname} × ${cname}」的种植记录？`, '删除确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await plantingsApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}
</script>

<template>
  <div class="toolbar">
    <el-select
      v-model="filterFieldId"
      placeholder="按地块过滤（全部）"
      clearable
      style="width: 220px"
      @change="load"
    >
      <el-option v-for="f in fields" :key="f.id" :label="f.name" :value="f.id" />
    </el-select>
    <el-button type="primary" :icon="Plus" :disabled="!fields.length || !crops.length" @click="openCreate">
      新增种植记录
    </el-button>
    <el-button :icon="Refresh" circle title="刷新" @click="load" />
    <span v-if="!fields.length || !crops.length" class="hint">
      需先创建地块与作物，才能登记种植记录
    </span>
  </div>

  <el-table :data="list" v-loading="loading" border stripe>
    <el-table-column prop="id" label="ID" width="64" />
    <el-table-column label="地块" min-width="130">
      <template #default="{ row }">{{ row.field_name ?? `#${row.field_id}` }}</template>
    </el-table-column>
    <el-table-column label="作物" min-width="120">
      <template #default="{ row }">{{ row.crop_name ?? `#${row.crop_id}` }}</template>
    </el-table-column>
    <el-table-column prop="sowing_date" label="播种日期" width="115" />
    <el-table-column label="预计收获" width="115">
      <template #default="{ row }">{{ row.expected_harvest_date ?? '—' }}</template>
    </el-table-column>
    <el-table-column label="状态" width="100">
      <template #default="{ row }">
        <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
          {{ PLANTING_STATUS_LABELS[row.status as PlantingStatus] }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="notes" label="备注" min-width="120" show-overflow-tooltip />
    <el-table-column label="操作" width="150" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="openEdit(row)">编辑</el-button>
        <el-button size="small" type="danger" plain @click="removeRow(row)">删除</el-button>
      </template>
    </el-table-column>
    <template #empty>暂无种植记录</template>
  </el-table>

  <el-dialog
    v-model="dialogVisible"
    :title="editingId == null ? '新增种植记录' : `编辑种植记录 #${editingId}`"
    width="540px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="地块" prop="field_id">
        <el-select v-model="form.field_id" style="width: 100%" :disabled="editingId != null">
          <el-option v-for="f in fields" :key="f.id" :label="f.name" :value="f.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="作物" prop="crop_id">
        <el-select v-model="form.crop_id" style="width: 100%" :disabled="editingId != null" @change="autoFillHarvest">
          <el-option v-for="c in crops" :key="c.id" :label="`${c.name}${c.variety ? ' · ' + c.variety : ''}`" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="播种日期" prop="sowing_date">
        <el-date-picker
          v-model="form.sowing_date"
          type="date"
          value-format="YYYY-MM-DD"
          style="width: 100%"
          @change="autoFillHarvest"
        />
      </el-form-item>
      <el-form-item label="预计收获">
        <el-date-picker
          v-model="form.expected_harvest_date"
          type="date"
          value-format="YYYY-MM-DD"
          style="width: 100%"
        />
        <div class="hint">选定作物与播种日期后按生命周期天数自动推算，可修改</div>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="form.status" style="width: 100%">
          <el-option
            v-for="(label, value) in PLANTING_STATUS_LABELS"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
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
  align-items: center;
}
.hint {
  color: #8a978a;
  font-size: 12px;
}
</style>
