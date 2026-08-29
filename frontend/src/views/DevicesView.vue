<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { devicesApi } from '../api'
import { errMsg } from '../api/http'
import { useCrudDialog } from '../composables/useCrudDialog'
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
    ElMessage.error(errMsg(e))
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

/* ---------- 表单弹窗（通用逻辑见 composables/useCrudDialog） ---------- */
interface DeviceForm {
  code: string
  name: string
  type: DeviceType
  model: string
  status: DeviceStatus
  notes: string
}

const rules: FormRules = {
  code: [{ required: true, message: '请输入设备编号', trigger: 'blur' }],
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  type: [{ required: true, message: '请选择载体类型', trigger: 'change' }],
}

const {
  dialogVisible, editingId, submitting, formRef, form,
  openCreate, openEdit, submit, removeRow,
} = useCrudDialog<Device, DeviceForm>({
  reload: load,
  create: (p) => devicesApi.create(p as never),
  update: (id, p) => devicesApi.update(id, p as never),
  remove: (id) => devicesApi.remove(id),
  emptyForm: () => ({ code: '', name: '', type: 'rover', model: '', status: 'idle', notes: '' }),
  toForm: (row) => ({
    code: row.code,
    name: row.name,
    type: row.type,
    model: row.model ?? '',
    status: row.status,
    notes: row.notes ?? '',
  }),
  entityName: '设备',
})

function buildPayload(f: DeviceForm, editing: boolean) {
  const payload: Record<string, unknown> = {
    name: f.name.trim(),
    type: f.type,
    model: f.model || null,
    status: f.status,
    notes: f.notes || null,
  }
  if (!editing) payload.code = f.code.trim()
  return payload
}

function onSubmit() {
  submit(buildPayload)
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
        <el-button size="small" type="danger" plain @click="removeRow(row, row.name)">删除</el-button>
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
      <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
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
