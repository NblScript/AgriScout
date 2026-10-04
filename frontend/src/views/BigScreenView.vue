<script setup lang="ts">
/**
 * 展示屏 /screen（计划 0018）：工作台的全屏放大版，给答辩投影和棚口大屏用；与全站同一套浅色视觉，宽屏时字号放大一档。
 * 顶部是全部大棚的概况，下面逐个大棚轮播：「垄 × 株」状态网格（含今日计划描边与进度）+ 棚内环境 + 等人确认；大田只列最近巡检。
 * 数据与工作台同源（useGreenhouseBoard），每分钟自动刷新；刷新失败保留上一次的数据并写明是几点的。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { FullScreen, House, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import ConfirmPanel from '../components/ConfirmPanel.vue'
import EnvPanel from '../components/EnvPanel.vue'
import PlantGrid from '../components/PlantGrid.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import StatCard from '../components/ui/StatCard.vue'
import { latestReadingAt, planProgress, stateCounts, statesUpdatedAt, useGreenhouseBoard } from '../composables/useGreenhouseBoard'
import { ANALYSIS_STATUS_LABELS, FACILITY_LABELS, type Patrol } from '../types'
import { fieldClock, fieldDateLabel, fieldTimeHms, relativeTime } from '../utils/fieldTime'

/** 每个大棚停留秒数、自动刷新间隔 */
const ROTATE_SECONDS = 20
const REFRESH_SECONDS = 60

const route = useRoute()
const router = useRouter()
const board = useGreenhouseBoard()
const { loaded, loadedAt, cards, openFields, confirmTasks, confirmCapped, confirmByField, todayPlan } = board

const now = ref(Date.now())
const failed = ref(false)

async function refresh() {
  try {
    await board.load()
    failed.value = false
  } catch {
    failed.value = true
  }
}

/* ---------- 轮播：按地块 id 记当前棚（每次刷新会按环境风险重排） ---------- */
const currentId = ref<number | null>(Number(route.query.field) || null)
const current = computed(() => cards.value.find((c) => c.field.id === currentId.value) ?? cards.value[0] ?? null)
const playing = ref(true)
const hovering = ref(false)
const elapsed = ref(0)
const canRotate = computed(() => cards.value.length > 1)

function select(id: number) {
  currentId.value = id
  elapsed.value = 0
}
function step(delta: number) {
  const list = cards.value
  if (!list.length) return
  const index = Math.max(list.findIndex((c) => c.field.id === current.value?.field.id), 0)
  select(list[(index + delta + list.length) % list.length].field.id)
}

let ticker: ReturnType<typeof setInterval> | null = null
let sinceRefresh = 0
function tick() {
  now.value = Date.now()
  sinceRefresh += 1
  if (sinceRefresh >= REFRESH_SECONDS) {
    sinceRefresh = 0
    void refresh()
  }
  if (playing.value && !hovering.value && canRotate.value && document.visibilityState === 'visible') {
    elapsed.value += 1
    if (elapsed.value >= ROTATE_SECONDS) step(1)
  }
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'ArrowRight') step(1)
  else if (event.key === 'ArrowLeft') step(-1)
}

/* ---------- 全屏 ---------- */
const fullscreen = ref(false)
function toggleFullscreen() {
  if (document.fullscreenElement) void document.exitFullscreen()
  else void document.documentElement.requestFullscreen?.().catch(() => undefined)
}
function onFullscreenChange() {
  fullscreen.value = !!document.fullscreenElement
}

onMounted(() => {
  void refresh()
  ticker = setInterval(tick, 1000)
  window.addEventListener('keydown', onKey)
  document.addEventListener('fullscreenchange', onFullscreenChange)
})
onBeforeUnmount(() => {
  if (ticker) clearInterval(ticker)
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
})

/* ---------- 全部大棚的概况 ---------- */
const totals = computed(() => {
  const sum = { plants: 0, early: 0, symptomatic: 0, reshoot: 0, planned: 0 }
  for (const card of cards.value) {
    const counts = stateCounts(card.states)
    sum.plants += card.states.length
    sum.early += counts.early
    sum.symptomatic += counts.symptomatic
    const plan = todayPlan(card)
    if (plan) {
      sum.planned += 1
      sum.reshoot += plan.reshoot.length
    }
  }
  return sum
})
const topRisk = computed(() => cards.value.find((c) => c.env?.index.env_index != null) ?? null)

/* ---------- 当前大棚 ---------- */
const currentPlan = computed(() => (current.value ? todayPlan(current.value) : null))
const currentTasks = computed(() => confirmTasks.value.filter((t) => t.field_id === current.value?.field.id))
const statesAt = computed(() => (current.value ? statesUpdatedAt(current.value.states) : null))
/** 今日计划进度：不算已作废的任务 */
const progress = computed(() => planProgress(currentPlan.value))
const chartFont = window.innerWidth >= 1600 ? 13 : 12

function patrolText(patrol: Patrol | null): string {
  if (!patrol) return '还没有巡检'
  return `#${patrol.id} · ${fieldClock(patrol.started_at)} · ${ANALYSIS_STATUS_LABELS[patrol.analysis_status] ?? patrol.analysis_status}`
}
</script>

<template>
  <div class="screen">
    <header class="top">
      <div class="brand">
        <span class="logo" aria-hidden="true">巡</span>
        <span class="brand-text"><b>大棚实时状态</b><small>巡知 · 设施大棚病害主动巡检</small></span>
      </div>
      <div class="clock">
        <b>{{ fieldTimeHms(now) }}</b>
        <span>{{ fieldDateLabel(now) }}</span>
      </div>
      <div class="top-right">
        <span class="sync" :class="{ failed }" aria-live="polite">
          <i class="dot" aria-hidden="true" />
          <template v-if="failed && loadedAt">刷新失败，显示的是 {{ fieldClock(loadedAt) }} 的数据</template>
          <template v-else-if="failed">加载失败，每分钟自动重试</template>
          <template v-else-if="loadedAt">数据 {{ fieldClock(loadedAt) }} 更新 · 每分钟自动刷新</template>
          <template v-else>正在加载…</template>
        </span>
        <el-button v-if="canRotate" :icon="playing ? VideoPause : VideoPlay" @click="playing = !playing">
          {{ playing ? '暂停轮播' : '继续轮播' }}
        </el-button>
        <el-button :icon="FullScreen" @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '全屏' }}</el-button>
        <el-button :icon="House" @click="router.push('/home')">工作台</el-button>
      </div>
    </header>

    <section class="kpis">
      <StatCard compact label="大棚" :value="loaded ? cards.length : null" unit="个"
                :hint="`在册 ${totals.plants} 株 · 大田 ${openFields.length} 块`" />
      <StatCard compact label="最高环境风险（近 72 小时）" :value="topRisk?.env?.index.env_index ?? null" :precision="2"
                :empty-text="loaded ? '环境数据不足' : '—'"
                :hint="topRisk ? `${topRisk.field.name} · 读数 ${relativeTime(latestReadingAt(topRisk.env), now)}` : '没有大棚有足够的温湿度读数'" />
      <StatCard compact label="今日叶背补拍" :value="loaded ? totals.reshoot : null" unit="株"
                :hint="`${totals.planned} / ${cards.length} 个大棚已生成今日计划`" />
      <StatCard compact label="等人确认" :value="loaded ? confirmTasks.length : null" :unit="confirmCapped ? '株以上' : '株'"
                hint="模型推荐、等人确认的株" />
      <StatCard compact label="需关注的株" :value="loaded ? totals.early + totals.symptomatic : null" unit="株"
                :hint="`早期 ${totals.early} · 明显 ${totals.symptomatic}（含模型占位）`" />
    </section>

    <nav v-if="cards.length" class="tabs" aria-label="大棚">
      <button v-for="card in cards" :key="card.field.id" type="button" class="tab"
              :class="{ on: card.field.id === current?.field.id }"
              :aria-current="card.field.id === current?.field.id ? 'true' : undefined" @click="select(card.field.id)">
        <span class="tab-name">{{ card.field.name }}</span>
        <span class="tab-meta">
          <template v-if="card.env?.index.env_index != null">环境风险 <b>{{ card.env.index.env_index.toFixed(2) }}</b></template>
          <template v-else>环境数据不足</template>
          · 待确认 <b>{{ confirmByField.get(card.field.id) ?? 0 }}</b>
        </span>
        <i v-if="canRotate && card.field.id === current?.field.id" class="tab-progress" aria-hidden="true"
           :style="{ width: `${(elapsed / ROTATE_SECONDS) * 100}%` }" />
      </button>
    </nav>

    <main v-if="current" class="main" @mouseenter="hovering = true" @mouseleave="hovering = false">
      <SectionCard class="grid-card">
        <template #title>
          <div class="gh-title">
            <h2>{{ current.field.name }}</h2>
            <p>
              {{ FACILITY_LABELS[current.field.facility_type ?? 'open_field'] }} · 在册 {{ current.states.length }} 株 ·
              <template v-if="statesAt">株状态依据 {{ fieldClock(statesAt) }}（{{ relativeTime(statesAt, now) }}）的巡检与人工确认</template>
              <template v-else>还没有巡检结果</template>
            </p>
          </div>
        </template>
        <template #actions>
          <div class="gh-meta">
            <span v-if="progress && currentPlan">
              今日计划 {{ fieldClock(currentPlan.generated_at) }} 生成 · <b>{{ progress.total }}</b> 株 · 已完成 <b>{{ progress.done }}</b>
            </span>
            <span v-else>今日计划未生成<template v-if="current.plan">（最近一次 {{ current.plan.plan_date }}）</template></span>
            <span>最近巡检 {{ patrolText(current.lastPatrol) }}</span>
          </div>
        </template>
        <PlantGrid :key="current.field.id" :states="current.states" :plan="currentPlan" fit="both" :max-cell="72" />
      </SectionCard>
      <div class="side">
        <EnvPanel :env="current.env" :now="now" :font-size="chartFont" class="side-env" />
        <ConfirmPanel :tasks="currentTasks" :limit="4" />
      </div>
    </main>
    <SectionCard v-else-if="loaded" class="main">
      <EmptyState title="还没有大棚" description="在「大棚与地块」里新建地块，设施类型选日光温室或塑料大棚，再批量建株档案。" />
    </SectionCard>
    <div v-else class="main"><el-skeleton animated :rows="10" /></div>

    <footer class="foot">
      <span class="foot-title">大田</span>
      <span v-for="item in openFields" :key="item.field.id" class="foot-item">
        <b>{{ item.field.name }}</b> 最近巡检 {{ patrolText(item.lastPatrol) }}
      </span>
      <span v-if="loaded && !openFields.length" class="foot-item">没有大田地块</span>
      <span class="foot-hint">鼠标停在大棚内容上暂停轮播 · 键盘 ← → 切换大棚</span>
    </footer>
  </div>
</template>

<style scoped>
.screen {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  gap: var(--space-4);
  height: 100vh;
  padding: var(--space-4) var(--space-5);
  background: var(--bg-page);
  overflow: hidden;
}
/* 宽屏（投影 1920）字号整体放大一档：只覆盖本页的字号令牌，组件随之放大 */
@media (min-width: 1600px) {
  .screen {
    --fs-12: 13px; --lh-12: 20px;
    --fs-13: 15px; --lh-13: 22px;
    --fs-14: 16px; --lh-14: 24px;
    --fs-16: 18px; --lh-16: 26px;
    --fs-20: 24px; --lh-20: 32px;
    --fs-24: 30px; --lh-24: 38px;
    --fs-30: 36px; --lh-30: 44px;
  }
}

.top { display: flex; align-items: center; gap: var(--space-6); min-width: 0; }
.brand { display: flex; align-items: center; gap: var(--space-3); }
.logo {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--brand-600);
  color: #fff;
  font-size: var(--fs-20);
  font-weight: var(--fw-semibold);
}
.brand-text { display: flex; flex-direction: column; }
.brand-text b { font-size: var(--fs-20); line-height: var(--lh-20); font-weight: var(--fw-semibold); color: var(--text-primary); }
.brand-text small { font-size: var(--fs-12); line-height: var(--lh-12); color: var(--text-secondary); }
.clock { display: flex; align-items: baseline; gap: var(--space-3); }
.clock b { font-size: var(--fs-24); line-height: var(--lh-24); font-weight: var(--fw-semibold); font-variant-numeric: tabular-nums; }
.clock span { font-size: var(--fs-14); color: var(--text-secondary); }
.top-right { display: flex; align-items: center; gap: var(--space-2); margin-left: auto; }
.top-right :deep(.el-button + .el-button) { margin-left: 0; }
.sync { display: inline-flex; align-items: center; gap: 6px; margin-right: var(--space-3); font-size: var(--fs-13); color: var(--text-secondary); }
.sync .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success); }
.sync.failed { color: var(--danger-ink); }
.sync.failed .dot { background: var(--danger); }

.kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-4); }

.tabs { display: flex; gap: var(--space-3); overflow-x: auto; padding-bottom: 2px; }
.tab {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  flex: 0 1 300px;
  min-width: 220px;
  padding: var(--space-2) var(--space-4) var(--space-3);
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.tab:hover { border-color: var(--brand-300); }
.tab.on { border-color: var(--brand-600); box-shadow: inset 0 0 0 1px var(--brand-600); background: var(--brand-50); }
.tab-name { font-size: var(--fs-16); line-height: var(--lh-16); font-weight: var(--fw-semibold); color: var(--text-primary); }
.tab-meta { font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-secondary); white-space: nowrap; }
.tab-meta b { font-variant-numeric: tabular-nums; color: var(--text-primary); font-weight: var(--fw-semibold); }
.tab-progress { position: absolute; left: 0; bottom: 0; height: 3px; background: var(--brand-600); transition: width 1s linear; }

.main { display: grid; grid-template-columns: minmax(0, 1fr) clamp(420px, 31vw, 600px); gap: var(--space-4); min-height: 0; }
.grid-card { display: flex; flex-direction: column; min-height: 0; }
.grid-card :deep(.sc-body) { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.grid-card :deep(.plant-grid) { flex: 1; }
.gh-title h2 { margin: 0; font-size: var(--fs-20); line-height: var(--lh-20); font-weight: var(--fw-semibold); color: var(--text-primary); }
.gh-title p { margin: 2px 0 0; font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-secondary); }
.gh-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-secondary); white-space: nowrap; }
.gh-meta b { font-variant-numeric: tabular-nums; font-weight: var(--fw-semibold); color: var(--text-primary); }
/* 右栏：环境卡吃掉剩余高度（曲线随之伸缩），确认卡按内容高 */
.side { display: flex; flex-direction: column; gap: var(--space-4); min-height: 0; }
.side > * { flex: none; }
.side > .side-env { flex: 1 1 auto; min-height: 0; }

.foot { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-2) var(--space-5); font-size: var(--fs-13); color: var(--text-secondary); }
.foot-title { font-weight: var(--fw-semibold); color: var(--text-primary); }
.foot-item b { font-weight: var(--fw-medium); color: var(--text-primary); margin-right: var(--space-1); }
.foot-hint { margin-left: auto; color: var(--text-placeholder); }

/* 矮屏或窄屏：不再锁一屏高，改为整页纵向滚动，网格卡给固定高度 */
@media (max-height: 760px), (max-width: 1199px) {
  .screen { height: auto; min-height: 100vh; overflow: visible; }
  .main { grid-template-columns: minmax(0, 1fr); }
  .grid-card { height: 520px; }
  .side > .side-env { flex: none; }
}
@media (max-width: 1199px) {
  .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .top { flex-wrap: wrap; gap: var(--space-3); }
}
</style>
