<script setup lang="ts">
/** 大棚详情 · 巡检记录：这块地最近的巡检，点一行进巡检回放（大棚按株回放，大田按地图回放）。 */
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Camera } from '@element-plus/icons-vue'
import EmptyState from '../../components/ui/EmptyState.vue'
import SectionCard from '../../components/ui/SectionCard.vue'
import { FIELD_PATROL_LIMIT, useFieldDetail } from '../../composables/useFieldDetail'
import { ANALYSIS_STATUS_LABELS, type Patrol } from '../../types'
import { fieldClock } from '../../utils/fieldTime'

const d = useFieldDetail()
const router = useRouter()
onMounted(() => { void d.patrols.load() })

function open(row: Patrol) {
  void router.push(`/patrols/${row.id}`)
}
function statusType(status: string): 'success' | 'danger' | 'warning' | 'info' {
  return status === 'done' ? 'success' : status === 'error' ? 'danger' : status === 'running' ? 'warning' : 'info'
}
</script>

<template>
  <SectionCard flush :title="`共 ${d.patrols.data.value.total} 次巡检`"
               :subtitle="d.patrols.data.value.total > FIELD_PATROL_LIMIT ? `这里列最近 ${FIELD_PATROL_LIMIT} 次，更早的在「巡检记录」页` : '按开始时间从新到旧'">
    <el-table :data="d.patrols.data.value.items" v-loading="d.patrols.loading.value" row-class-name="clickable" @row-click="open">
      <el-table-column label="巡检" width="90">
        <template #default="{ row }"><span class="tabular">#{{ row.id }}</span></template>
      </el-table-column>
      <el-table-column label="开始" min-width="130">
        <template #default="{ row }"><span class="tabular">{{ fieldClock(row.started_at) }}</span></template>
      </el-table-column>
      <el-table-column label="结束" min-width="130">
        <template #default="{ row }"><span class="tabular">{{ fieldClock(row.ended_at) }}</span></template>
      </el-table-column>
      <el-table-column label="设备" min-width="130">
        <template #default="{ row }">{{ row.device_code ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="分析" width="100">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" :type="statusType(row.analysis_status)">
            {{ ANALYSIS_STATUS_LABELS[row.analysis_status as Patrol['analysis_status']] ?? row.analysis_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="" width="96" align="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click.stop="open(row)">回放</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <EmptyState :icon="Camera" title="还没有巡检" description="小车上传巡检包后在这里出现" />
      </template>
    </el-table>
  </SectionCard>
</template>

<style scoped>
:deep(.clickable) { cursor: pointer; }
</style>
