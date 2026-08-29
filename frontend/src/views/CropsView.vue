<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { cropsApi } from '../api'
import { errMsg } from '../api/http'
import type { Crop } from '../types'

const list = ref<Crop[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    list.value = await cropsApi.list()
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

interface StageRow {
  name: string
  days: number | null
}

const form = reactive({
  name: '',
  variety: '',
  lifecycle_days: null as number | null,
  stages: [] as StageRow[],
  description: '',
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入作物名称', trigger: 'blur' }],
  lifecycle_days: [{ required: true, message: '请输入生命周期天数', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    variety: '',
    lifecycle_days: null,
    stages: [{ name: '', days: null }],
    description: '',
  })
  dialogVisible.value = true
}

function openEdit(row: Crop) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    variety: row.variety ?? '',
    lifecycle_days: row.lifecycle_days,
    stages: row.stages.map((s) => ({ name: s.name, days: s.days })),
    description: row.description ?? '',
  })
  dialogVisible.value = true
}

function addStage() {
  form.stages.push({ name: '', days: null })
}

function removeStage(index: number) {
  form.stages.splice(index, 1)
}

function stagesDaysTotal(): number {
  return form.stages.reduce((sum, s) => sum + (s.days ?? 0), 0)
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  const cleanedStages = form.stages.filter((s) => s.name.trim() && s.days != null && s.days > 0)
  for (const s of cleanedStages) {
    if (!s.days || s.days < 1) {
      ElMessage.warning(`生育期「${s.name}」的天数需为正整数`)
      return
    }
  }
  const total = cleanedStages.reduce((sum, s) => sum + (s.days ?? 0), 0)
  if (cleanedStages.length > 0 && total !== (form.lifecycle_days ?? -1)) {
    ElMessage.warning(`生育期天数合计 ${total} 天，与生命周期 ${form.lifecycle_days} 天不一致`)
    return
  }

  submitting.value = true
  const payload = {
    name: form.name.trim(),
    variety: form.variety || null,
    lifecycle_days: form.lifecycle_days!,
    stages: cleanedStages.map((s) => ({ name: s.name.trim(), days: s.days! })),
    description: form.description || null,
  }
  try {
    if (editingId.value == null) {
      await cropsApi.create(payload)
      ElMessage.success('作物已创建')
    } else {
      await cropsApi.update(editingId.value, payload)
      ElMessage.success('作物已更新')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    submitting.value = false
  }
}

async function removeRow(row: Crop) {
  try {
    await ElMessageBox.confirm(`确认删除作物「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await cropsApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
</script>

<template>
  <div class="toolbar">
    <el-button type="primary" :icon="Plus" @click="openCreate">新增作物</el-button>
    <el-button :icon="Refresh" circle title="刷新" @click="load" />
  </div>

  <el-table :data="list" v-loading="loading" border stripe>
    <el-table-column prop="id" label="ID" width="64" />
    <el-table-column prop="name" label="名称" min-width="120" />
    <el-table-column label="品种" min-width="120">
      <template #default="{ row }">{{ row.variety ?? '—' }}</template>
    </el-table-column>
    <el-table-column prop="lifecycle_days" label="生命周期(天)" width="120" />
    <el-table-column label="生育期" min-width="260">
      <template #default="{ row }">
        <el-tag
          v-for="(s, i) in row.stages"
          :key="i"
          size="small"
          effect="plain"
          class="stage-tag"
        >
          {{ s.name }}·{{ s.days }}天
        </el-tag>
        <span v-if="!row.stages.length">—</span>
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
    :title="editingId == null ? '新增作物' : `编辑作物 #${editingId}`"
    width="620px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="如：冬小麦" maxlength="100" />
      </el-form-item>
      <el-form-item label="品种">
        <el-input v-model="form.variety" placeholder="如：济麦22" maxlength="100" />
      </el-form-item>
      <el-form-item label="生命周期(天)" prop="lifecycle_days">
        <el-input-number v-model="form.lifecycle_days" :min="1" :max="3650" />
        <span v-if="stagesDaysTotal() > 0" class="hint">
          生育期合计：{{ stagesDaysTotal() }} 天
          <em v-if="stagesDaysTotal() !== (form.lifecycle_days ?? -1)" class="warn">（不一致）</em>
        </span>
      </el-form-item>
      <el-form-item label="生育期">
        <div class="stage-editor">
          <div v-for="(s, i) in form.stages" :key="i" class="stage-row">
            <el-input v-model="s.name" placeholder="名称，如：拔节期" maxlength="30" />
            <el-input-number v-model="s.days" :min="1" :max="3650" controls-position="right" />
            <el-button size="small" text type="danger" @click="removeStage(i)">删</el-button>
          </div>
          <el-button size="small" text type="primary" @click="addStage">+ 添加生育期</el-button>
        </div>
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="2" />
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
.stage-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}
.stage-editor {
  width: 100%;
}
.stage-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}
.hint {
  margin-left: 12px;
  color: #8a978a;
  font-size: 12px;
}
.warn {
  color: #c67a28;
  font-style: normal;
}
</style>
