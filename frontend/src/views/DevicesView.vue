<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { devicesApi } from '../api'
import {
  DEVICE_STATUS_LABELS,
  DEVICE_TYPE_LABELS,
  type Device,
  type DeviceStatus,
  type DeviceType,
} from '../types'

const list = ref<Device[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    list.value = await devicesApi.list()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

const STATUS_TAG: Record<DeviceStatus, 'info' | 'success' | 'warning' | 'danger'> = {
  idle: 'info',
  active: 'success',
  maintenance: 'warning',
  offline: 'danger',
}

/* ---------- 表单弹窗 ---------- */
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  code: '',
  name: '',
  type: 'rover' as DeviceType,
  model: '',
  status: 'idle' as DeviceStatus,
  notes: '',
})

const rules: FormRules = {
  code: [{ required: true, message: '请输入设备编号', trigger: 'blur' }],
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  type: [{ required: true, message: '请选择载体类型', trigger: 'change' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { code: '', name: '', type: 'rover', model: '', status: 'idle', notes: '' })
  dialogVisible.value = true
}

function openEdit(row: Device) {
  editingId.value = row.id
  Object.assign(form, {
    code: row.code,
    name: row.name,
    type: row.type,
    model: row.model ?? '',
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
      await devicesApi.create({
        code: form.code.trim(),
        name: form.name.trim(),
        type: form.type,
        model: form.model || null,
        status: form.status,
        notes: form.notes || null,
      })
      ElMessage.success('设备已创建')
    } else {
      await devicesApi.update(editingId.value, {
        name: form.name.trim(),
        type: form.type,
        model: form.model || null,
        status: form.status,
        notes: form.notes || null,
      })
      ElMessage.success('设备已更新')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    submitting.value = false
  }
}

async function removeRow(row: Device) {
  try {
    await ElMessageBox.confirm(`确认删除设备「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await devicesApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}
</script>

<template>
  <div class="toolbar">
    <el-button type="primary" :icon="Plus" @click="openCreate">新增设备</el-button>
    <el-button :icon="Refresh" circle title="刷新" @click="load" />
  </div>

  <el-table :data="list" v-loading="loading" border stripe>
    <el-table-column prop="id" label="ID" width="64" />
    <el-table-column prop="code" label="编号" min-width="110" />
    <el-table-column prop="name" label="名称" min-width="130" />
    <el-table-column label="类型" width="110">
      <template #default="{ row }">{{ DEVICE_TYPE_LABELS[row.type as DeviceType] }}</template>
    </el-table-column>
    <el-table-column label="型号" min-width="120">
      <template #default="{ row }">{{ row.model ?? '—' }}</template>
    </el-table-column>
    <el-table-column label="状态" width="100">
      <template #default="{ row }">
        <el-tag :type="STATUS_TAG[row.status as DeviceStatus]" effect="plain">
          {{ DEVICE_STATUS_LABELS[row.status as DeviceStatus] }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="150" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="openEdit(row)">编辑</el-button>
        <el-button size="small" type="danger" plain @click="removeRow(row)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>

  <el-dialog
    v-model="dialogVisible"
    :title="editingId == null ? '新增设备' : `编辑设备 #${editingId}`"
    width="520px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="编号" prop="code">
        <el-input
          v-model="form.code"
          placeholder="如：sim-001"
          maxlength="50"
          :disabled="editingId != null"
        />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="如：模拟巡检车" maxlength="100" />
      </el-form-item>
      <el-form-item label="载体类型" prop="type">
        <el-select v-model="form.type" style="width: 100%">
          <el-option
            v-for="(label, value) in DEVICE_TYPE_LABELS"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="型号">
        <el-input v-model="form.model" maxlength="100" />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="form.status" style="width: 100%">
          <el-option
            v-for="(label, value) in DEVICE_STATUS_LABELS"
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
}
</style>
