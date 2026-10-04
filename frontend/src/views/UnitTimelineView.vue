<script setup lang="ts">
/**
 * 单株时间线（计划 0014，计划 0018 阶段 B 改版）：顶上是当前状态和人工确认，下面照片按田间日期分组、正面叶背分栏。
 * 人工结论写成标注，挂在回看期内最近一张合格叶背图上，每株状态以最近一次人工结论为准（计划 0015）；
 * 提交后这株未完成的「确认」任务一并关掉（D19）。手机宽度可用。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import ConfirmForm from '../components/plant/ConfirmForm.vue'
import PhotoDays from '../components/plant/PhotoDays.vue'
import PlantStatus from '../components/plant/PlantStatus.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import TaskTypeTag from '../components/ui/TaskTypeTag.vue'
import { greenhouseApi, observationUnitsApi, softwareLoopApi } from '../api'
import { errMsg } from '../api/http'
import { useBreadcrumb } from '../composables/useBreadcrumb'
import { fieldHomePath } from '../layouts/nav'
import { useFieldsStore } from '../stores/fields'
import { useUiStore } from '../stores/ui'
import type { PlantState, RevisitTask, UnitTimeline } from '../types'
import { confirmTarget } from '../utils/plantPhotos'
import { taskReasons } from '../utils/planTask'

const route = useRoute()
const router = useRouter()
const fieldsStore = useFieldsStore()
const ui = useUiStore()
const unitId = Number(route.params.id)

const timeline = ref<UnitTimeline | null>(null)
const plantState = ref<PlantState | null>(null)
const stateLoaded = ref(false)
const openTasks = ref<RevisitTask[]>([])
const loading = ref(false)
const days = ref(30)
const now = ref(Date.now())

const unit = computed(() => timeline.value?.unit ?? null)
const field = computed(() => (unit.value ? fieldsStore.byId.get(unit.value.field_id) : undefined))

// 面包屑能一键回到所属大棚（计划 0018 设计 3）
useBreadcrumb(() => [
  { label: '大棚与地块', to: '/fields' },
  ...(unit.value ? [
    { label: field.value?.name ?? `地块 #${unit.value.field_id}`, to: field.value ? fieldHomePath(field.value) : undefined },
    { label: '株档案', to: `/fields/${unit.value.field_id}/units` },
  ] : []),
  { label: unit.value?.key ?? `株 #${unitId}` },
])

async function load() {
  loading.value = true
  now.value = Date.now()
  try {
    timeline.value = await observationUnitsApi.timeline(unitId, days.value)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
  const fieldId = timeline.value?.unit.field_id
  if (fieldId == null) return
  ui.setCurrentField(fieldId)
  document.title = `${timeline.value!.unit.key} · 单株时间线 · 巡知`
  void fieldsStore.load().catch(() => { /* 面包屑退回显示地块编号 */ })
  await Promise.all([loadState(fieldId), loadTasks(fieldId)])
}

/** 当前状态按整块地算（与计划同一口径），这里只取本株；拿不到不影响时间线 */
async function loadState(fieldId: number) {
  try {
    plantState.value = (await greenhouseApi.plantStates(fieldId)).find((s) => s.unit_id === unitId) ?? null
  } catch {
    plantState.value = null
  } finally {
    stateLoaded.value = true
  }
}
/** 这株在不在待确认里：在就写原因，确认时顺手关掉 */
async function loadTasks(fieldId: number) {
  try {
    openTasks.value = (await softwareLoopApi.openTasks('label', { field_id: fieldId })).tasks
      .filter((t) => t.observation_unit_id === unitId)
  } catch {
    openTasks.value = []
  }
}

onMounted(() => {
  if (!Number.isInteger(unitId) || unitId <= 0) {
    void router.replace({ name: 'fields' })
    return
  }
  void load()
})

const photos = computed(() => (timeline.value?.days ?? []).flatMap((d) => d.photos))
const target = computed(() => confirmTarget(photos.value))
const photoCount = computed(() => photos.value.length)
const reasons = computed(() => [...new Set(openTasks.value.flatMap(taskReasons))])
</script>

<template>
  <PageHeader :title="unit?.key ?? `株 #${unitId}`" subtitle="单株时间线：每天正面、叶背分栏；人工确认的结论决定这株的当前状态">
    <template #meta>
      <template v-if="unit">
        <span class="chip">
          <template v-if="unit.row_no != null">第 {{ unit.row_no }} 垄 · 第 {{ unit.position_no }} 株</template>
          <template v-else>自定义株号</template>
        </span>
        <span v-if="unit.tag_code" class="chip">标签 {{ unit.tag_code }}</span>
        <el-tag v-if="unit.status === 'retired'" type="info" size="small" effect="plain">已停用</el-tag>
        <router-link v-if="field" :to="fieldHomePath(field)" class="field-link">{{ field.name }}</router-link>
      </template>
    </template>
    <template #actions>
      <el-select v-model="days" style="width: 128px" aria-label="回看天数" @change="load">
        <el-option :value="7" label="回看 7 天" />
        <el-option :value="30" label="回看 30 天" />
        <el-option :value="90" label="回看 90 天" />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </template>
  </PageHeader>

  <div class="top">
    <SectionCard title="当前状态">
      <PlantStatus :state="plantState" :loaded="stateLoaded" :now="now" />
      <div v-if="openTasks.length" class="queue">
        <TaskTypeTag type="label" />
        <span class="text-13">在待确认里<template v-if="reasons.length">：{{ reasons.join('、') }}</template></span>
      </div>
    </SectionCard>
    <SectionCard title="人工确认" subtitle="看完叶背图选一个结论；「其他」记为不明">
      <ConfirmForm v-if="unit" :unit-id="unit.id" :field-id="unit.field_id" :target="target" :tasks="openTasks"
                   :loading="loading" @done="load" />
      <el-skeleton v-else animated :rows="2" />
    </SectionCard>
  </div>

  <SectionCard title="照片" :subtitle="`回看 ${days} 天 · ${photoCount} 张；灰显为质量不合格，绿框是确认会挂上的那张`">
    <div v-loading="loading && !timeline">
      <PhotoDays :days="timeline?.days ?? []" :target-id="target?.capture_point_id ?? null" />
    </div>
  </SectionCard>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  font-size: var(--fs-12);
  color: var(--text-secondary);
}
.field-link { font-size: var(--fs-13); }
.top {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.queue {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border);
  color: var(--text-secondary);
}
@media (max-width: 1023px) {
  .top { grid-template-columns: minmax(0, 1fr); }
}
</style>
