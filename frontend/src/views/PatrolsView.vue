<script setup lang="ts">
/** 巡检记录：全部巡检，按地块、分析状态筛选，点一行进巡检回放（计划 0018 阶段 B 换外壳）。 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Camera, Refresh } from '@element-plus/icons-vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import { fieldsApi, patrolsApi } from '../api'
import { errMsg } from '../api/http'
import type { Field, Patrol, TimeWarning } from '../types'
import { fieldClock } from '../utils/fieldTime'

const route = useRoute()
const router = useRouter()
const list = ref<Patrol[]>([])
const fields = ref<Field[]>([])
const loading = ref(false)
/** 地址栏带 ?field_id= 时预选该地块（工作台、顶栏地块切换器跳过来） */
function queryFieldId(): number | null {
  const value = Number(route.query.field_id)
  return Number.isInteger(value) && value > 0 ? value : null
}
const filterFieldId = ref<number | null>(queryFieldId())
watch(() => route.query.field_id, () => {
  if (route.name !== 'patrols') return // 正在离开本页
  filterFieldId.value = queryFieldId()
  void load()
})
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
    ElMessage.error(errMsg(e))
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

/** 后端时间一律 UTC（带时区），按田间时区显示（D9） */
function fmtTime(_row: Patrol, _col: unknown, value: string | null) {
  return fieldClock(value)
}

const ANALYSIS_TAG: Record<string, 'info' | 'warning' | 'success' | 'danger'> = {
  pending: 'info',
  running: 'warning',
  done: 'success',
  error: 'danger',
}
const ANALYSIS_TEXT: Record<string, string> = { pending: '待分析', running: '分析中', done: '已完成', error: '失败' }
const DATA_TEXT: Record<string, string> = { received: '已接收' }
</script>

<template>
  <PageHeader title="巡检记录" subtitle="小车每上传一个巡检包就是一次巡检；点一行打开回放（大棚按株，大田按地图）">
    <template #actions>
      <el-select v-model="filterFieldId" placeholder="全部地块" clearable class="f-field" @change="load">
        <el-option v-for="f in fields" :key="f.id" :label="f.name" :value="f.id" />
      </el-select>
      <el-select v-model="filterAnalysis" placeholder="全部分析状态" clearable class="f-status" @change="load">
        <el-option label="待分析" value="pending" />
        <el-option label="分析中" value="running" />
        <el-option label="已完成" value="done" />
        <el-option label="失败" value="error" />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </template>
  </PageHeader>

  <SectionCard flush>
    <el-table :data="list" v-loading="loading" row-class-name="clickable" @row-click="open">
      <el-table-column label="巡检" width="80">
        <template #default="{ row }"><span class="tabular">#{{ row.id }}</span></template>
      </el-table-column>
      <el-table-column label="地块" min-width="160">
        <template #default="{ row }">{{ row.field_name ?? `#${row.field_id}` }}</template>
      </el-table-column>
      <el-table-column label="设备" width="140">
        <template #default="{ row }">{{ row.device_code ?? '—' }}</template>
      </el-table-column>
      <el-table-column prop="started_at" label="开始时间" min-width="150" :formatter="fmtTime" class-name="tabular" />
      <el-table-column prop="ended_at" label="结束时间" min-width="150" :formatter="fmtTime" class-name="tabular" />
      <el-table-column label="时钟" width="100">
        <template #default="{ row }">
          <el-tooltip v-if="row.time_warnings?.length" placement="top"
                      :content="row.time_warnings.map((w: TimeWarning) => w.message).join('；')">
            <el-tag size="small" type="warning" effect="plain">时间存疑</el-tag>
          </el-tooltip>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="数据" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'received' ? 'success' : 'info'" effect="plain">
            {{ DATA_TEXT[row.status] ?? row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="分析状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="ANALYSIS_TAG[row.analysis_status] ?? 'info'" effect="plain">
            {{ ANALYSIS_TEXT[row.analysis_status] ?? row.analysis_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="" width="96" align="right" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click.stop="open(row)">回放</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState :icon="Camera" title="还没有巡检" description="小车上传巡检包后在这里出现；也可以先用模拟器跑一趟虚拟巡检" />
      </template>
    </el-table>
  </SectionCard>
</template>

<style scoped>
.f-field { width: 200px; }
.f-status { width: 150px; }
:deep(.clickable) { cursor: pointer; }
</style>
