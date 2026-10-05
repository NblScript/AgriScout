<script setup lang="ts">
/**
 * 待确认（计划 0018 阶段 B）：未完成的「确认」任务（label）按株合并、按优先级排，每条带最近叶背缩略图；
 * 点开侧滑面板看照片，选 健康 / 早期 / 明显 / 其他 提交后自动跳下一株，也可以跳过。
 * 确认沿用单株时间线的机制（标注 + 关掉这株的确认任务，D19），不加接口。手机宽度面板占满屏。
 * 研究闭环按采样点生成、没有对应株的确认任务，面板里给巡检回放的入口（在那里标注）。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, Picture, Refresh, Stamp } from '@element-plus/icons-vue'
import ConfirmForm from '../components/plant/ConfirmForm.vue'
import PhotoDays from '../components/plant/PhotoDays.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import QualityBadge from '../components/ui/QualityBadge.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import StateTag from '../components/ui/StateTag.vue'
import { softwareLoopApi } from '../api'
import { errMsg } from '../api/http'
import { PHONE_QUERY, useMediaQuery } from '../composables/useMediaQuery'
import { useTimelineCache } from '../composables/useTimelineCache'
import { useAuthStore } from '../stores/auth'
import { useFieldsStore } from '../stores/fields'
import { useUiStore } from '../stores/ui'
import type { RevisitTask, TimelinePhoto } from '../types'
import { fieldClock } from '../utils/fieldTime'
import { confirmTarget, photoSide, previewPhoto, timelineAccepted, timelineQuality } from '../utils/plantPhotos'
import { taskModelScore, taskPlantState, taskReasons, taskUnitKey } from '../utils/planTask'

const PAGE_SIZE = 20

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const fieldsStore = useFieldsStore()
const ui = useUiStore()
const phone = useMediaQuery(PHONE_QUERY)
const cache = useTimelineCache()

const tasks = ref<RevisitTask[]>([])
const capped = ref(false)
const loading = ref(false)
const queryField = Number(route.query.field_id)
const fieldFilter = ref<number | null>(Number.isInteger(queryField) && queryField > 0 ? queryField : null)
const page = ref(1)

async function load() {
  loading.value = true
  try {
    const result = await softwareLoopApi.openTasks('label', { field_id: fieldFilter.value ?? undefined, limit: 500 })
    tasks.value = result.tasks
    capped.value = result.capped
    if (fieldFilter.value == null) void ui.refreshConfirmCount(true)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void fieldsStore.load().catch(() => { /* 缺地块名只显示编号 */ })
  void load()
})
function onFilter() {
  page.value = 1
  void router.replace({ query: fieldFilter.value ? { field_id: String(fieldFilter.value) } : {} })
  void load()
}

/* ---------- 按株合并：同一株可能有几天的确认任务，确认一次全关 ---------- */
interface QueueItem { key: string; unitId: number | null; fieldId: number; lead: RevisitTask; tasks: RevisitTask[] }
const items = computed<QueueItem[]>(() => {
  const byUnit = new Map<number, QueueItem>()
  const list: QueueItem[] = []
  for (const task of tasks.value) {
    const unitId = task.observation_unit_id
    const existing = unitId != null ? byUnit.get(unitId) : undefined
    if (existing) {
      existing.tasks.push(task)
      continue
    }
    const item = { key: unitId != null ? `u${unitId}` : `t${task.id}`, unitId, fieldId: task.field_id, lead: task, tasks: [task] }
    if (unitId != null) byUnit.set(unitId, item)
    list.push(item)
  }
  return list
})
const pageItems = computed(() => items.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
watch(items, (list) => {
  if (page.value > 1 && (page.value - 1) * PAGE_SIZE >= list.length) page.value = Math.max(1, Math.ceil(list.length / PAGE_SIZE))
})
// 只取当前页这些株的时间线（缩略图），面板里直接复用
watch(pageItems, (list) => list.forEach((item) => item.unitId != null && cache.request(item.unitId)), { immediate: true })

const fieldNames = computed(() => new Map(fieldsStore.list.map((f) => [f.id, f.name])))
function fieldName(id: number) { return fieldNames.value.get(id) ?? `地块 #${id}` }
function sourceText(task: RevisitTask): string {
  const value = task.rationale.source
  return value === 'human' ? '人工' : value === 'model' ? '模型占位' : ''
}
function photosOf(unitId: number | null): TimelinePhoto[] {
  return (cache.get(unitId)?.data?.days ?? []).flatMap((d) => d.photos)
}
function previewOf(item: QueueItem): TimelinePhoto | null {
  return previewPhoto(photosOf(item.unitId))
}
function photoCaption(photo: TimelinePhoto): string {
  return `${photoSide(photo.view) === 'under' ? '叶背' : '正面'} ${fieldClock(photo.captured_at)}`
}

/* ---------- 侧滑面板 ---------- */
const activeKey = ref<string | null>(null)
const drawerOpen = ref(false)
const active = computed(() => items.value.find((i) => i.key === activeKey.value) ?? null)
const activeIndex = computed(() => (active.value ? items.value.indexOf(active.value) : -1))
const activeEntry = computed(() => cache.get(active.value?.unitId))
const activeTarget = computed(() => confirmTarget(photosOf(active.value?.unitId ?? null)))
const activeHero = computed(() => activeTarget.value ?? (active.value ? previewOf(active.value) : null))

function open(item: QueueItem) {
  activeKey.value = item.key
  drawerOpen.value = true
  if (item.unitId != null) cache.request(item.unitId, true)
  void nextTick(() => document.querySelector('.confirm-drawer .el-drawer__body')?.scrollTo(0, 0))
  // 面板里翻到别的页的株，列表也跟过去
  page.value = Math.floor(items.value.indexOf(item) / PAGE_SIZE) + 1
}
function step(delta: number) {
  const next = items.value[activeIndex.value + delta]
  if (next) open(next)
  else {
    drawerOpen.value = false
    if (delta > 0) ElMessage.info('已经是最后一株了')
  }
}
/** 提交后：这株的任务都关了，从列表拿掉，跳到原来排在它后面的那株 */
function onDone() {
  const item = active.value
  if (!item) return
  const index = activeIndex.value
  if (item.unitId != null) cache.invalidate(item.unitId)
  const closedIds = new Set(item.tasks.map((t) => t.id))
  tasks.value = tasks.value.filter((t) => !closedIds.has(t.id))
  const next = items.value[index] ?? null
  if (next) open(next)
  else {
    drawerOpen.value = false
    ElMessage.success('这批都确认完了')
  }
}
</script>

<template>
  <PageHeader title="待确认" subtitle="模型推荐、等人看叶背照片确认的株；点一条打开照片，提交后自动跳到下一株">
    <template #actions>
      <el-select v-model="fieldFilter" placeholder="全部大棚" clearable class="field-select" @change="onFilter">
        <el-option v-for="f in fieldsStore.list" :key="f.id" :label="f.name" :value="f.id" />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </template>
  </PageHeader>

  <SectionCard :title="`${items.length}${capped ? '+' : ''} 株待确认`"
               :subtitle="tasks.length > items.length ? `共 ${tasks.length} 条确认任务，同一株合并成一条；按优先级从高到低` : '按优先级从高到低'" flush>
    <ul v-if="pageItems.length" v-loading="loading" class="queue">
      <li v-for="item in pageItems" :key="item.key">
        <button type="button" class="item" :class="{ current: drawerOpen && item.key === activeKey }" @click="open(item)">
          <span class="thumb">
            <template v-if="item.unitId != null">
              <img v-if="previewOf(item)?.photo_url" :src="previewOf(item)!.photo_url!" alt="" loading="lazy"
                   :class="{ bad: timelineAccepted(previewOf(item)!) === false }">
              <el-skeleton v-else-if="cache.get(item.unitId)?.loading" animated>
                <template #template><el-skeleton-item variant="image" class="sk" /></template>
              </el-skeleton>
              <span v-else class="no-photo"><el-icon><Picture /></el-icon></span>
            </template>
            <span v-else class="no-photo text-12">采样点</span>
          </span>
          <span class="body">
            <span class="line1">
              <b class="key">{{ taskUnitKey(item.lead) }}</b>
              <span class="muted text-13 ellipsis">{{ fieldName(item.fieldId) }}</span>
            </span>
            <span class="line2">
              <StateTag v-if="taskPlantState(item.lead)" :state="taskPlantState(item.lead)!" size="small" />
              <span v-if="sourceText(item.lead)" class="muted text-12">{{ sourceText(item.lead) }}</span>
              <span class="muted text-12">模型分 <b class="num">{{ taskModelScore(item.lead) }}</b></span>
            </span>
            <span v-if="taskReasons(item.lead).length" class="reasons">
              <el-tag v-for="r in taskReasons(item.lead)" :key="r" size="small" type="info" effect="plain">{{ r }}</el-tag>
            </span>
            <span class="line4 muted text-12">
              <template v-if="previewOf(item)">{{ photoCaption(previewOf(item)!) }} · </template>
              计划日 {{ (item.lead.parameters.plan_date as string | undefined) ?? fieldClock(item.lead.created_at) }}
              <template v-if="item.tasks.length > 1"> · {{ item.tasks.length }} 条任务</template>
            </span>
          </span>
          <span class="go">
            <span class="go-text">{{ auth.isViewer || item.unitId == null ? '查看' : '去确认' }}</span>
            <el-icon><ArrowRight /></el-icon>
          </span>
        </button>
      </li>
    </ul>
    <div v-else-if="loading" class="pad"><el-skeleton animated :rows="5" /></div>
    <EmptyState v-else :icon="Stamp" title="没有等人确认的株"
                description="生成巡检计划后，模型判为早期或分数超过确认阈值的株会出现在这里。" />
    <div v-if="items.length > PAGE_SIZE" class="pager">
      <el-pagination v-model:current-page="page" :page-size="PAGE_SIZE" :total="items.length"
                     layout="prev, pager, next" :pager-count="5" small background />
    </div>
  </SectionCard>

  <el-drawer v-model="drawerOpen" :size="phone ? '100%' : '680px'" append-to-body class="confirm-drawer">
    <template #header>
      <div v-if="active" class="d-head">
        <span class="d-title">{{ taskUnitKey(active.lead) }}</span>
        <span class="muted text-13">{{ fieldName(active.fieldId) }} · 第 {{ activeIndex + 1 }} / {{ items.length }} 株</span>
      </div>
    </template>

    <div v-if="active" class="d-body">
      <div class="d-facts">
        <StateTag v-if="taskPlantState(active.lead)" :state="taskPlantState(active.lead)!" size="small" />
        <span class="muted text-13">
          计划时{{ sourceText(active.lead) ? `依据${sourceText(active.lead)}` : '' }} · 模型分 {{ taskModelScore(active.lead) }}
        </span>
        <router-link v-if="active.unitId != null" :to="`/units/${active.unitId}`" class="text-13">打开单株时间线</router-link>
      </div>
      <div v-if="taskReasons(active.lead).length" class="reasons">
        <el-tag v-for="r in taskReasons(active.lead)" :key="r" size="small" type="info" effect="plain">{{ r }}</el-tag>
      </div>

      <template v-if="active.unitId != null">
        <p v-if="activeEntry?.error" class="error text-13">照片没取到：{{ activeEntry.error }}</p>
        <figure v-if="activeHero" class="hero">
          <el-image v-if="activeHero.photo_url" :src="activeHero.photo_url" :preview-src-list="[activeHero.photo_url]"
                    fit="contain" preview-teleported />
          <figcaption>
            <span class="text-13">{{ activeHero === activeTarget ? '要确认的叶背' : '最近一张' }} · {{ photoCaption(activeHero) }}</span>
            <QualityBadge :quality="timelineQuality(activeHero)" :accepted="timelineAccepted(activeHero)" />
          </figcaption>
        </figure>
        <el-skeleton v-else-if="activeEntry?.loading" animated>
          <template #template><el-skeleton-item variant="image" class="hero-sk" /></template>
        </el-skeleton>
        <h3 class="d-sub">近 30 天照片</h3>
        <PhotoDays v-if="activeEntry?.data" :days="activeEntry.data.days" :target-id="activeTarget?.capture_point_id ?? null" />
        <el-skeleton v-else-if="activeEntry?.loading" animated :rows="4" />
      </template>
      <EmptyState v-else compact title="这条确认任务没有对应的株"
                  description="是研究闭环按采样点生成的，到巡检回放里看图标注。">
        <el-button v-if="active.lead.patrol_id" type="primary" size="small"
                   @click="router.push(`/patrols/${active.lead.patrol_id}`)">打开巡检回放 #{{ active.lead.patrol_id }}</el-button>
      </EmptyState>
    </div>

    <template #footer>
      <ConfirmForm v-if="active && active.unitId != null && !auth.isViewer" compact
                   :unit-id="active.unitId" :field-id="active.fieldId" :target="activeTarget" :tasks="active.tasks"
                   :loading="activeEntry?.loading ?? true" @done="onDone">
        <template #extra><el-button @click="step(1)">跳过</el-button></template>
      </ConfirmForm>
      <div v-else class="nav">
        <span v-if="auth.isViewer" class="muted text-13">只读账号只能看照片</span>
        <span class="nav-buttons">
          <el-button :icon="ArrowLeft" :disabled="activeIndex <= 0" @click="step(-1)">上一株</el-button>
          <el-button @click="step(1)">下一株<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
        </span>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.field-select { width: 200px; }
.queue { list-style: none; margin: 0; padding: 0; }
.queue li + li { border-top: 1px solid var(--border); }
.item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  width: 100%;
  padding: var(--space-3) var(--space-5);
  border: 0;
  background: none;
  font: inherit;
  text-align: left;
  color: var(--text-primary);
  cursor: pointer;
}
.item:hover, .item.current { background: var(--bg-hover); }
.item:focus-visible { outline: 2px solid var(--brand-600); outline-offset: -2px; }
.thumb { flex: none; width: 104px; height: 78px; border-radius: var(--radius-sm); overflow: hidden; background: var(--bg-subtle); }
.thumb img { display: block; width: 100%; height: 100%; object-fit: cover; }
.thumb img.bad { filter: grayscale(1); opacity: 0.55; }
.thumb .sk { width: 104px; height: 78px; }
.no-photo { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-placeholder); }
.body { display: flex; flex-direction: column; gap: var(--space-1); flex: 1; min-width: 0; }
.line1, .line2 { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.key { font-family: var(--font-mono); font-size: var(--fs-14); font-weight: var(--fw-semibold); }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.num { font-weight: var(--fw-medium); color: var(--text-primary); font-variant-numeric: tabular-nums; }
.reasons { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.line4 { font-variant-numeric: tabular-nums; }
.go { display: inline-flex; align-items: center; gap: 2px; align-self: center; color: var(--el-color-primary); font-size: var(--fs-13); white-space: nowrap; }
.pad { padding: var(--space-4) var(--space-5); }
.pager { display: flex; justify-content: center; padding: var(--space-3); border-top: 1px solid var(--border); }

.d-head { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.d-title { font-family: var(--font-mono); font-size: var(--fs-20); line-height: var(--lh-20); font-weight: var(--fw-semibold); color: var(--text-primary); }
.d-body { display: flex; flex-direction: column; gap: var(--space-3); }
.d-facts { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); }
.hero { margin: 0; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.hero :deep(.el-image) { display: block; width: 100%; aspect-ratio: 4 / 3; max-height: 420px; background: var(--neutral-900); }
.hero figcaption { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-2) var(--space-3); }
.hero-sk { width: 100%; height: 280px; }
.d-sub { margin: var(--space-2) 0 0; font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text-primary); }
.error { margin: 0; color: var(--danger-ink); }
.nav { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); }
.nav-buttons { display: inline-flex; gap: var(--space-2); margin-left: auto; }
.nav-buttons :deep(.el-button + .el-button) { margin-left: 0; }

@media (max-width: 767px) {
  .field-select { width: 160px; }
  .item { gap: var(--space-3); padding: var(--space-3) var(--space-4); }
  .thumb { width: 84px; height: 63px; }
  .go-text { display: none; }
}
</style>

<style>
/* 抽屉挂在 body 上，scoped 选不到：底栏留白和分隔线 */
.confirm-drawer .el-drawer__header { margin-bottom: 0; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--border); }
.confirm-drawer .el-drawer__body { padding: var(--space-4) var(--space-5); }
.confirm-drawer .el-drawer__footer { padding: var(--space-3) var(--space-5); border-top: 1px solid var(--border); background: var(--bg-card); }
@media (max-width: 767px) {
  .confirm-drawer .el-drawer__header, .confirm-drawer .el-drawer__body, .confirm-drawer .el-drawer__footer { padding-left: var(--space-4); padding-right: var(--space-4); }
}
</style>
