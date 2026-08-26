<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { fieldsApi, patrolsApi } from '../api'
import type { Field, Patrol } from '../types'

const router = useRouter()
const list = ref<Patrol[]>([])
const fields = ref<Field[]>([])
const loading = ref(false)
const filterFieldId = ref<number | null>(null)
const filterAnalysis = ref<string>('')

async function load() {
  loading.value = true
  try {
    const page = await patrolsApi.list({
      field_id: filterFieldId.value ?? undefined,
      analysis_status: filterAnalysis.value || undefined,
    })
    list.value = page.items
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    fields.value = await fieldsApi.list()
  } catch { /* 过滤器缺地块列表不致命 */ }
})

function open(row: Patrol) {
  router.push(`/patrols/${row.id}`)
}

const ANALYSIS_TAG: Record<string, 'info' | 'warning' | 'success' | 'danger'> = {
  pending: 'info',
  running: 'warning',
  done: 'success',
  error: 'danger',
}
</script>

<template>
  <div class="toolbar">
    <el-select
      v-model="filterFieldId"
      placeholder="按地块过滤（全部）"
      clearable
      style="width: 200px"
      @change="load"
    >
      <el-option v-for="f in fields" :key="f.id" :label="f.name" :value="f.id" />
    </el-select>
    <el-select
      v-model="filterAnalysis"
      placeholder="分析状态（全部）"
      clearable
      style="width: 160px"
      @change="load"
    >
      <el-option label="待分析" value="pending" />
      <el-option label="分析中" value="running" />
      <el-option label="已完成" value="done" />
      <el-option label="失败" value="error" />
    </el-select>
    <el-button :icon="Refresh" circle title="刷新" @click="load" />
  </div>

  <el-table :data="list" v-loading="loading" border stripe @row-click="open">
    <el-table-column prop="id" label="ID" width="64" />
    <el-table-column label="地块" min-width="150">
      <template #default="{ row }">{{ row.field_name ?? `#${row.field_id}` }}</template>
    </el-table-column>
    <el-table-column label="设备" width="110">
      <template #default="{ row }">{{ row.device_code ?? '—' }}</template>
    </el-table-column>
    <el-table-column prop="started_at" label="开始时间" min-width="160" />
    <el-table-column prop="ended_at" label="结束时间" min-width="160" />
    <el-table-column label="数据" width="90">
      <template #default="{ row }">
        <el-tag :type="row.status === 'received' ? 'success' : 'info'" effect="plain">
          {{ row.status }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="分析状态" width="100">
      <template #default="{ row }">
        <el-tag :type="ANALYSIS_TAG[row.analysis_status] ?? 'info'" effect="plain">
          {{ row.analysis_status }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="" width="100" fixed="right">
      <template #default="{ row }">
        <el-button size="small" type="primary" plain @click.stop="open(row)">回放</el-button>
      </template>
    </el-table-column>
    <template #empty>暂无巡检任务——先用模拟器生成一趟虚拟巡田</template>
  </el-table>
</template>

<style scoped>
.toolbar {
  margin-bottom: 14px;
  display: flex;
  gap: 10px;
}
:deep(.el-table__row) {
  cursor: pointer;
}
</style>
