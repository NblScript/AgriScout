<script setup lang="ts">
/**
 * 数字孪生大棚 /twin（数媒大赛）：全屏深色 3D 页，把一个大棚的「垄 × 株」状态、今日巡检计划和巡检车放进立体场景。
 * 数据与展示屏同源（每株状态、最近计划、棚内环境三个现有接口），每分钟刷新；株集合不变时只换颜色，不打断镜头和巡检车。
 * 巡检车的行驶是按今日计划回放的演示动画，不是车的实时位置；点任意一株在右侧看状态、入选理由和最近照片。
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Aim, Back, Camera, FullScreen, MagicStick, Moon, Refresh, Sunny, VideoPause, VideoPlay,
} from '@element-plus/icons-vue'
import { greenhouseApi, observationUnitsApi } from '../api'
import { errMsg } from '../api/http'
import { GreenhouseScene, type Facility, type RoverStatus, type TwinPalette, type TwinPlant } from '../components/twin/greenhouseScene'
import { PLAN_LISTS, planProgress, stateCounts } from '../composables/useGreenhouseBoard'
import { useFieldsStore } from '../stores/fields'
import { cssVar } from '../styles/tokens'
import {
  isGreenhouse, PLAN_LIST_LABELS, PLAN_LIST_SHORT_LABELS, PLAN_TRIGGER_LABELS, PLANT_SOURCE_LABELS, PLANT_STATE_LABELS,
  type EnvSummary, type PatrolPlan, type PlanItem, type PlanListName, type PlantState, type PlantStateValue, type TimelinePhoto,
} from '../types'
import { fieldClock, fieldDate, fieldDateLabel, fieldTimeHms } from '../utils/fieldTime'
import { photoSide } from '../utils/plantPhotos'

const REFRESH_SECONDS = 60
const STATE_ORDER: PlantStateValue[] = ['healthy', 'early', 'symptomatic', 'unknown']
const STATE_SHAPES: Record<PlantStateValue, string> = { healthy: '●', early: '▲', symptomatic: '■', unknown: '○' }

const route = useRoute()
const router = useRouter()
const fieldsStore = useFieldsStore()

const host = ref<HTMLDivElement | null>(null)
const scene = shallowRef<GreenhouseScene | null>(null)

const greenhouses = computed(() => fieldsStore.list.filter((f) => isGreenhouse(f)))
const fieldId = ref<number | null>(Number(route.query.field) || null)
const field = computed(() => greenhouses.value.find((f) => f.id === fieldId.value) ?? null)

const states = ref<PlantState[]>([])
const plan = ref<PatrolPlan | null>(null)
const env = ref<EnvSummary | null>(null)
const loading = ref(false)
const error = ref('')
const loadedAt = ref<number | null>(null)
const now = ref(Date.now())

/* ---------- 画面开关 ---------- */
const playing = ref(true)
const autoRotate = ref(false)
const heatOn = ref(false)
const dawn = ref(true)
const fullscreen = ref(false)

/* ---------- 计划与株 ---------- */
const planItems = computed(() => {
  const map = new Map<number, PlanItem>()
  if (!plan.value) return map
  for (const name of PLAN_LISTS) {
    for (const item of plan.value[name]) if (item.task_status !== 'cancelled') map.set(item.unit_id, item)
  }
  return map
})
const isTodayPlan = computed(() => plan.value?.plan_date === fieldDate(now.value))
const counts = computed(() => stateCounts(states.value))
const progress = computed(() => planProgress(plan.value))
/** 株状态环：conic-gradient 按占比分段，颜色与图例同源 */
const ring = computed(() => {
  const total = states.value.length
  if (!total) return 'conic-gradient(var(--twin-panel-border) 0 100%)'
  const color: Record<PlantStateValue, string> = {
    healthy: 'var(--twin-healthy)', early: 'var(--state-early)', symptomatic: 'var(--twin-symptomatic)', unknown: 'var(--twin-unknown)',
  }
  let at = 0
  const stops = STATE_ORDER.map((s) => {
    const from = at
    at += (counts.value[s] / total) * 100
    return `${color[s]} ${from}% ${at}%`
  })
  return `conic-gradient(${stops.join(', ')})`
})
const attention = computed(() => counts.value.early + counts.value.symptomatic)
const progressPct = computed(() => (progress.value?.total ? Math.round((progress.value.done / progress.value.total) * 100) : 0))
const listCounts = computed(() => {
  const out = {} as Record<PlanListName, number>
  for (const name of PLAN_LISTS) out[name] = plan.value?.[name].filter((i) => i.task_status !== 'cancelled').length ?? 0
  return out
})

function toTwinPlants(): TwinPlant[] {
  return states.value.map((s) => {
    const item = planItems.value.get(s.unit_id)
    return {
      unitId: s.unit_id,
      key: s.key,
      row: s.row_no,
      pos: s.position_no,
      state: s.state,
      risk: s.model_score ?? (item ? Math.min(1, item.score) : null),
      list: item?.list_name ?? null,
    }
  })
}

/** 巡检车要去的株：补拍、全覆盖、抽查三张名单（确认名单是推给人看照片，不用车再去） */
function roverOrder(): number[] {
  if (!plan.value) return []
  return (['reshoot', 'coverage', 'random'] as PlanListName[])
    .flatMap((name) => plan.value![name])
    .filter((item) => item.task_status !== 'cancelled')
    .map((item) => item.unit_id)
}

/* ---------- 取数 ---------- */
async function load(rebuild: boolean) {
  const id = fieldId.value
  if (id == null) return
  loading.value = true
  try {
    const [s, p, e] = await Promise.all([
      greenhouseApi.plantStates(id),
      greenhouseApi.latestPlan(id).catch(() => null), // 404 = 还没生成过计划
      greenhouseApi.env(id).catch(() => null),
    ])
    if (id !== fieldId.value) return
    states.value = s
    plan.value = p
    env.value = e
    error.value = ''
    loadedAt.value = Date.now()
    const plants = toTwinPlants()
    const facility: Facility = field.value?.facility_type === 'plastic_tunnel' ? 'plastic_tunnel' : 'solar_greenhouse'
    if (rebuild || !scene.value?.updateStates(plants)) {
      scene.value?.setData(plants, facility, roverOrder())
      selected.value = null
    }
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

function chooseField(id: number) {
  if (id === fieldId.value) return
  fieldId.value = id
  void router.replace({ query: { ...route.query, field: String(id) } })
}
watch(fieldId, () => void load(true))

/* ---------- 选株与悬停 ---------- */
const selected = ref<number | null>(null)
const hover = ref<{ unitId: number; x: number; y: number } | null>(null)
const stateOf = computed(() => new Map(states.value.map((s) => [s.unit_id, s])))
const selectedState = computed(() => (selected.value == null ? null : stateOf.value.get(selected.value) ?? null))
const selectedItem = computed(() => (selected.value == null ? null : planItems.value.get(selected.value) ?? null))
const hoverState = computed(() => (hover.value ? stateOf.value.get(hover.value.unitId) ?? null : null))

const photos = ref<TimelinePhoto[]>([])
const photosLoading = ref(false)
const photosError = ref('')
let photoToken = 0

watch(selected, async (unitId) => {
  photos.value = []
  photosError.value = ''
  if (unitId == null) return
  const token = ++photoToken
  photosLoading.value = true
  try {
    const timeline = await observationUnitsApi.timeline(unitId, 14)
    if (token !== photoToken) return
    photos.value = timeline.days.flatMap((d) => d.photos)
      .sort((a, b) => Date.parse(b.captured_at) - Date.parse(a.captured_at))
      .slice(0, 4)
  } catch (e) {
    if (token === photoToken) photosError.value = errMsg(e)
  } finally {
    if (token === photoToken) photosLoading.value = false
  }
})

function pickFromList(unitId: number) {
  selected.value = unitId
  scene.value?.select(unitId)
  scene.value?.focus(unitId)
}

function reasons(item: PlanItem | null): string[] {
  return ((item?.rationale.triggers as string[] | undefined) ?? []).map((t) => PLAN_TRIGGER_LABELS[t] ?? t)
}

/** 今日推给人确认的株（左侧清单） */
const confirmList = computed(() => (plan.value?.confirm ?? []).filter((i) => i.task_status !== 'cancelled').slice(0, 6))

/* ---------- 巡检车 ---------- */
const rover = ref<RoverStatus>({ phase: 'idle', unitId: null, index: 0, total: 0 })
const roverText = computed(() => {
  const r = rover.value
  const key = r.unitId == null ? '' : stateOf.value.get(r.unitId)?.key ?? ''
  const list = r.unitId == null ? null : planItems.value.get(r.unitId)?.list_name
  const what = list ? PLAN_LIST_SHORT_LABELS[list] : ''
  if (!r.total) return plan.value ? '今日计划没有要车去拍的株' : '还没有巡检计划，巡检车待命'
  if (r.phase === 'shooting') return `正在拍 ${key} · ${what} · 正面 + 叶背`
  if (r.phase === 'moving') return `前往 ${key} · ${what}`
  return '本轮拍完，返回棚口'
})

/* ---------- 环境 ---------- */
const lastHour = computed(() => {
  const hours = env.value?.hourly ?? []
  for (let i = hours.length - 1; i >= 0; i--) if (!hours[i].missing) return hours[i]
  return null
})
const envIndex = computed(() => env.value?.index.env_index ?? null)
const envLevel = computed(() => {
  const v = envIndex.value
  if (v == null) return { text: '数据不足', cls: 'none' }
  if (v >= 0.6) return { text: '高', cls: 'high' }
  if (v >= 0.3) return { text: '中', cls: 'mid' }
  return { text: '低', cls: 'low' }
})
const morning = computed(() => env.value?.morning_window ?? plan.value?.window ?? null)

/* ---------- 场景开关 ---------- */
watch(playing, (v) => { if (scene.value) scene.value.playing = v })
watch(autoRotate, (v) => scene.value?.setAutoRotate(v))
watch(heatOn, (v) => scene.value?.setHeatVisible(v))
watch(dawn, (v) => scene.value?.setLightMode(v ? 'dawn' : 'day'))

function toggleFullscreen() {
  if (document.fullscreenElement) void document.exitFullscreen()
  else void document.documentElement.requestFullscreen?.().catch(() => undefined)
}
function onFullscreenChange() {
  fullscreen.value = !!document.fullscreenElement
}

function saveShot() {
  const url = scene.value?.snapshot()
  if (!url) return
  const a = document.createElement('a')
  a.href = url
  a.download = `数字孪生-${field.value?.name ?? '大棚'}-${fieldDate()}.png`
  a.click()
}

function palette(): TwinPalette {
  return {
    state: {
      healthy: cssVar('--twin-healthy', '#2f9f79'),
      early: cssVar('--state-early', '#e9a823'),
      symptomatic: cssVar('--twin-symptomatic', '#e2574c'),
      unknown: cssVar('--twin-unknown', '#7f8c86'),
    },
    task: {
      confirm: cssVar('--twin-confirm', '#9b6cf0'),
      reshoot: cssVar('--twin-reshoot', '#5b8ef5'),
      coverage: cssVar('--task-coverage', '#38bdf8'),
      random: cssVar('--task-random', '#8a94a6'),
    },
    bgTop: cssVar('--twin-bg-top', '#0b1a1f'),
    bgBottom: cssVar('--twin-bg-bottom', '#16302c'),
    ground: cssVar('--twin-ground', '#0f1f1c'),
    floor: cssVar('--twin-floor', '#1c2f2a'),
    soil: cssVar('--twin-soil', '#4a3a2c'),
    wall: cssVar('--twin-wall', '#5b5148'),
    frame: cssVar('--twin-frame', '#b9c7c2'),
    film: cssVar('--twin-film', '#bfe9f2'),
    accent: cssVar('--twin-accent', '#3ee0c5'),
    rover: cssVar('--twin-rover', '#eef3f1'),
    heatLow: cssVar('--twin-heat-low', '#2a9d6f'),
    heatMid: cssVar('--twin-heat-mid', '#f0b429'),
    heatHigh: cssVar('--twin-heat-high', '#e0412f'),
  }
}

let ticker: ReturnType<typeof setInterval> | null = null
let sinceRefresh = 0

onMounted(async () => {
  scene.value = new GreenhouseScene(host.value!, palette(), {
    onPick: (unitId) => { selected.value = unitId },
    onHover: (unitId, x, y) => { hover.value = unitId == null ? null : { unitId, x, y } },
    onRover: (status) => { rover.value = status },
  })
  document.addEventListener('fullscreenchange', onFullscreenChange)
  ticker = setInterval(() => {
    now.value = Date.now()
    sinceRefresh += 1
    if (sinceRefresh >= REFRESH_SECONDS) {
      sinceRefresh = 0
      void load(false)
    }
  }, 1000)
  try {
    await fieldsStore.load()
  } catch (e) {
    error.value = errMsg(e)
    return
  }
  if (!field.value && greenhouses.value.length) chooseField(greenhouses.value[0].id)
  else void load(true)
})

onBeforeUnmount(() => {
  if (ticker) clearInterval(ticker)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  scene.value?.dispose()
})
</script>

<template>
  <div class="twin">
    <div ref="host" class="stage" />
    <div class="vignette" aria-hidden="true" />

    <!-- 顶栏 -->
    <header class="hud top">
      <div class="brand">
        <span class="logo" aria-hidden="true">瞳</span>
        <span class="brand-text"><b>禾瞳 AgriSight</b><small>设施大棚病害风险感知与智能巡检</small></span>
      </div>
      <nav class="fields" aria-label="切换大棚">
        <button v-for="f in greenhouses" :key="f.id" type="button" :class="{ on: f.id === fieldId }" @click="chooseField(f.id)">
          {{ f.name }}
        </button>
      </nav>
      <div class="title" aria-hidden="true">
        <b>{{ field?.name ?? '数字孪生大棚' }}</b>
        <span>数字孪生 · 病害风险态势</span>
      </div>
      <div class="clock">
        <b>{{ fieldTimeHms(now) }}</b>
        <span>{{ fieldDateLabel(now) }}</span>
      </div>
    </header>

    <!-- 左：全棚概况 -->
    <aside class="hud left">
      <section class="panel">
        <h3>全棚株状态</h3>
        <div class="overview">
          <div class="ring" :style="{ background: ring }" aria-hidden="true">
            <span><b>{{ states.length }}</b><small>株在册</small></span>
          </div>
          <div class="kpi">
            <span>需关注</span>
            <b :class="{ alert: attention > 0 }">{{ attention }}</b>
            <small>早期 {{ counts.early }} · 明显 {{ counts.symptomatic }}</small>
          </div>
        </div>
        <ul class="states">
          <li v-for="s in STATE_ORDER" :key="s" :class="`st-${s}`">
            <i aria-hidden="true">{{ STATE_SHAPES[s] }}</i>
            <span>{{ PLANT_STATE_LABELS[s] }}</span>
            <b>{{ counts[s] }}</b>
            <span class="bar" aria-hidden="true"><em :style="{ width: states.length ? `${(counts[s] / states.length) * 100}%` : '0' }" /></span>
          </li>
        </ul>
      </section>

      <section class="panel">
        <h3>
          {{ isTodayPlan ? '今日巡检计划' : '最近巡检计划' }}
          <small v-if="plan && !isTodayPlan">{{ plan.plan_date }}</small>
        </h3>
        <template v-if="plan">
          <ul class="lists">
            <li v-for="name in PLAN_LISTS" :key="name" :class="`task-${name}`">
              <i aria-hidden="true" />
              <span>{{ PLAN_LIST_LABELS[name] }}</span>
              <b>{{ listCounts[name] }}</b>
            </li>
          </ul>
          <p v-if="progress" class="progress">
            <span>已完成 <b>{{ progress.done }}</b> / {{ progress.total }}</span><b class="pct">{{ progressPct }}%</b>
            <span class="bar" aria-hidden="true"><em :style="{ width: `${progressPct}%` }" /></span>
          </p>
        </template>
        <p v-else class="dim">还没有生成过巡检计划</p>
      </section>

      <section v-if="confirmList.length" class="panel">
        <h3>今天请人确认</h3>
        <ul class="confirm">
          <li v-for="item in confirmList" :key="item.unit_id">
            <button type="button" @click="pickFromList(item.unit_id)">
              <b>{{ item.key }}</b>
              <span>{{ reasons(item)[0] ?? '风险靠前' }}</span>
            </button>
          </li>
        </ul>
      </section>
    </aside>

    <!-- 右：环境 + 选中株 -->
    <aside class="hud right">
      <section class="panel env">
        <h3>棚内环境</h3>
        <div class="env-grid">
          <div><span>温度</span><b>{{ lastHour?.temp_c != null ? `${lastHour.temp_c.toFixed(1)}℃` : '—' }}</b></div>
          <div><span>湿度</span><b>{{ lastHour?.humidity_pct != null ? `${Math.round(lastHour.humidity_pct)}%` : '—' }}</b></div>
          <div><span>发病环境风险</span><b :class="`lv-${envLevel.cls}`">{{ envIndex != null ? envIndex.toFixed(2) : '—' }} · {{ envLevel.text }}</b></div>
          <div><span>近 {{ env?.index.window_hours ?? 72 }} 小时湿润</span><b>{{ env ? `${env.index.wet_hours} 小时` : '—' }}</b></div>
        </div>
        <p v-if="morning" class="dim small">清晨叶背窗口 {{ morning.start }}–{{ morning.end }} · 前夜湿润 {{ morning.night_wet_hours }} 小时</p>
        <p v-if="lastHour" class="dim small">读数截至 {{ fieldClock(lastHour.hour) }}</p>
      </section>

      <transition name="slide">
        <section v-if="selected != null" class="panel plant">
          <header class="plant-head">
            <h3>{{ selectedState?.key ?? `株 #${selected}` }}</h3>
            <button type="button" class="x" aria-label="关闭" @click="selected = null; scene?.select(null)">×</button>
          </header>
          <template v-if="selectedState">
            <p class="plant-state" :class="`st-${selectedState.state}`">
              <i aria-hidden="true">{{ STATE_SHAPES[selectedState.state] }}</i>
              {{ PLANT_STATE_LABELS[selectedState.state] }}
              <span class="dim">· {{ PLANT_SOURCE_LABELS[selectedState.source] }}</span>
            </p>
            <dl class="facts">
              <div><dt>位置</dt><dd>第 {{ selectedState.row_no ?? '—' }} 垄 · 第 {{ selectedState.position_no ?? '—' }} 株</dd></div>
              <div><dt>模型分</dt><dd>{{ selectedState.model_score?.toFixed(2) ?? '—' }}</dd></div>
              <div><dt>最近拍到</dt><dd>{{ selectedState.last_seen_at ? fieldClock(selectedState.last_seen_at) : '还没有' }}</dd></div>
            </dl>
          </template>
          <div v-if="selectedItem" class="why" :class="`task-${selectedItem.list_name}`">
            <b>{{ isTodayPlan ? '今日' : '最近计划' }}：{{ PLAN_LIST_LABELS[selectedItem.list_name] }}</b>
            <span v-if="reasons(selectedItem).length">入选理由：{{ reasons(selectedItem).join('、') }}</span>
          </div>
          <p v-else class="dim small">不在{{ isTodayPlan ? '今日' : '最近' }}计划里</p>

          <h4>最近照片</h4>
          <p v-if="photosLoading" class="dim small">加载中…</p>
          <p v-else-if="photosError" class="dim small">照片取不到：{{ photosError }}</p>
          <p v-else-if="!photos.length" class="dim small">近两周没有拍到</p>
          <div v-else class="photos">
            <figure v-for="ph in photos" :key="ph.capture_point_id">
              <img v-if="ph.photo_url" :src="ph.photo_url" alt="" loading="lazy">
              <figcaption>{{ photoSide(ph.view) === 'under' ? '叶背' : '正面' }} · {{ fieldClock(ph.captured_at) }}</figcaption>
            </figure>
          </div>
          <router-link class="more" :to="`/units/${selected}`">打开单株时间线 →</router-link>
        </section>
      </transition>
    </aside>

    <!-- 底部：巡检车 + 图例 + 控制 -->
    <footer class="hud bottom">
      <div class="rover-line" aria-live="polite">
        <span class="pulse" :class="rover.phase" aria-hidden="true" />
        <b>巡检车</b>
        <span>{{ roverText }}</span>
        <span v-if="rover.total" class="dim">{{ rover.index }}/{{ rover.total }}</span>
      </div>
      <div class="legend">
        <span v-for="s in STATE_ORDER" :key="s" :class="`st-${s}`"><i>{{ STATE_SHAPES[s] }}</i>{{ PLANT_STATE_LABELS[s] }}</span>
        <span class="sep" />
        <span v-for="name in PLAN_LISTS" :key="name" :class="`task-${name}`"><em />{{ PLAN_LIST_SHORT_LABELS[name] }}</span>
      </div>
      <div class="controls">
        <button type="button" :aria-pressed="playing" :title="playing ? '暂停巡检演示' : '播放巡检演示'" @click="playing = !playing">
          <el-icon><component :is="playing ? VideoPause : VideoPlay" /></el-icon>{{ playing ? '暂停' : '播放' }}
        </button>
        <button type="button" :aria-pressed="autoRotate" :class="{ on: autoRotate }" @click="autoRotate = !autoRotate">
          <el-icon><MagicStick /></el-icon>漫游
        </button>
        <button type="button" :aria-pressed="heatOn" :class="{ on: heatOn }" @click="heatOn = !heatOn">
          <el-icon><Aim /></el-icon>风险热力
        </button>
        <button type="button" @click="dawn = !dawn">
          <el-icon><component :is="dawn ? Moon : Sunny" /></el-icon>{{ dawn ? '清晨' : '白天' }}
        </button>
        <button type="button" @click="scene?.resetView()"><el-icon><Refresh /></el-icon>复位</button>
        <button type="button" title="保存当前画面" @click="saveShot"><el-icon><Camera /></el-icon>截图</button>
        <button type="button" @click="toggleFullscreen"><el-icon><FullScreen /></el-icon>{{ fullscreen ? '退出全屏' : '全屏' }}</button>
        <router-link class="btn" to="/home"><el-icon><Back /></el-icon>返回</router-link>
      </div>
    </footer>

    <!-- 悬停提示 -->
    <div v-if="hover && hoverState" class="tip" :style="{ left: `${hover.x + 14}px`, top: `${hover.y + 14}px` }">
      <b>{{ hoverState.key }}</b>
      <span :class="`st-${hoverState.state}`">{{ STATE_SHAPES[hoverState.state] }} {{ PLANT_STATE_LABELS[hoverState.state] }}</span>
      <span v-if="planItems.get(hover.unitId)" class="dim">{{ PLAN_LIST_SHORT_LABELS[planItems.get(hover.unitId)!.list_name] }}</span>
    </div>

    <p v-if="error" class="hud banner">{{ error }}</p>
    <p v-else-if="loading && !loadedAt" class="hud banner">正在加载大棚数据…</p>
    <p v-else-if="loadedAt && !greenhouses.length" class="hud banner">还没有大棚地块，先在「大棚与地块」里建一个</p>
  </div>
</template>

<style scoped>
.twin {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: var(--twin-bg-bottom);
  color: var(--twin-text);
  font-family: var(--font-sans);
}
.stage {
  position: absolute;
  inset: 0;
}
/* 四周压暗、上下各一条渐变带，面板浮在画面上也读得清 */
.vignette {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background:
    linear-gradient(to bottom, rgba(4, 12, 15, 0.85), transparent 120px),
    linear-gradient(to top, rgba(4, 12, 15, 0.8), transparent 110px),
    radial-gradient(ellipse at 50% 55%, transparent 55%, rgba(2, 8, 10, 0.55) 100%);
}
.hud {
  position: absolute;
  z-index: 2;
  pointer-events: none;
}
.hud > *,
.hud .panel {
  pointer-events: auto;
}
.panel {
  position: relative;
  background: linear-gradient(160deg, var(--twin-panel-strong), var(--twin-panel) 60%);
  border: 1px solid var(--twin-panel-border);
  border-radius: 4px;
  padding: var(--space-3) var(--space-4) var(--space-4);
  backdrop-filter: blur(10px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(62, 224, 197, 0.08);
}
/* 左上、右下两个发光折角 */
.panel::before,
.panel::after {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  border: 2px solid var(--twin-accent);
  pointer-events: none;
  filter: drop-shadow(0 0 4px var(--twin-glow));
}
.panel::before { top: -1px; left: -1px; border-right: none; border-bottom: none; }
.panel::after { bottom: -1px; right: -1px; border-left: none; border-top: none; }
h3 {
  margin: 0 0 var(--space-3);
  padding: 0 0 var(--space-2) 10px;
  font-size: var(--fs-14);
  font-weight: var(--fw-semibold);
  letter-spacing: 0.12em;
  color: var(--twin-text);
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  position: relative;
  border-bottom: 1px solid transparent;
  border-image: linear-gradient(to right, var(--twin-panel-border), transparent) 1;
}
h3::before {
  content: '';
  position: absolute;
  left: 0;
  top: 3px;
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: var(--twin-accent);
  box-shadow: 0 0 8px var(--twin-glow);
}
h3 small {
  color: var(--twin-text-dim);
  font-weight: var(--fw-regular);
}
h4 {
  margin: var(--space-3) 0 var(--space-2);
  font-size: var(--fs-13);
  color: var(--twin-text-dim);
  font-weight: var(--fw-medium);
}
.dim {
  color: var(--twin-text-dim);
}
.small {
  font-size: var(--fs-12);
  margin: var(--space-1) 0 0;
}
b {
  font-variant-numeric: tabular-nums;
}

/* 顶栏 */
.top {
  top: var(--space-4);
  left: var(--space-4);
  right: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-5);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.logo {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 20px;
  color: var(--twin-bg-top);
  background: linear-gradient(135deg, var(--twin-accent), var(--twin-healthy));
  box-shadow: 0 0 18px var(--twin-glow);
}
.brand-text {
  display: flex;
  flex-direction: column;
}
.brand-text b {
  font-size: var(--fs-20);
  letter-spacing: 0.08em;
}
.brand-text small {
  font-size: var(--fs-12);
  color: var(--twin-text-dim);
}
.fields {
  display: flex;
  gap: 0;
  padding: 3px;
  border: 1px solid var(--twin-panel-border);
  border-radius: 6px;
  background: var(--twin-panel);
  backdrop-filter: blur(8px);
}
.fields button {
  border: none !important;
  background: transparent !important;
  border-radius: 4px !important;
  backdrop-filter: none !important;
}
.fields button.on {
  background: color-mix(in srgb, var(--twin-accent) 16%, transparent) !important;
}
/* 顶部居中的标题：梯形底板 + 发光下沿 */
.title {
  position: absolute;
  left: 50%;
  top: -16px;
  transform: translateX(-50%);
  min-width: 460px;
  padding: 14px 64px 12px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: linear-gradient(to bottom, rgba(10, 32, 34, 0.92), rgba(10, 32, 34, 0.6));
  clip-path: polygon(0 0, 100% 0, calc(100% - 36px) 100%, 36px 100%);
  pointer-events: none;
}
.title::after {
  content: '';
  position: absolute;
  left: 36px;
  right: 36px;
  bottom: 0;
  height: 2px;
  background: linear-gradient(to right, transparent, var(--twin-accent), transparent);
  box-shadow: 0 0 12px var(--twin-glow);
}
.title b {
  font-size: 26px;
  letter-spacing: 0.18em;
  text-shadow: 0 0 14px var(--twin-glow);
}
.title span {
  font-size: var(--fs-12);
  letter-spacing: 0.3em;
  color: var(--twin-accent);
}
.fields button,
.controls button,
.controls .btn {
  appearance: none;
  border: 1px solid var(--twin-panel-border);
  background: var(--twin-panel);
  color: var(--twin-text);
  border-radius: 999px;
  padding: 6px 14px;
  font: inherit;
  font-size: var(--fs-13);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  text-decoration: none;
  backdrop-filter: blur(8px);
}
.fields button.on,
.controls button.on {
  border-color: var(--twin-accent);
  color: var(--twin-accent);
  box-shadow: 0 0 12px rgba(62, 224, 197, 0.25) inset;
}
.fields button:hover,
.controls button:hover,
.controls .btn:hover {
  border-color: var(--twin-accent);
}
.clock {
  margin-left: auto;
  text-align: right;
  display: flex;
  flex-direction: column;
}
.clock b {
  font-size: var(--fs-24);
  letter-spacing: 0.06em;
  text-shadow: 0 0 10px var(--twin-glow);
}
.clock span {
  font-size: var(--fs-12);
  color: var(--twin-text-dim);
}

/* 左右栏 */
.left,
.right {
  top: 84px;
  bottom: 96px;
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  overflow: auto;
}
.left {
  left: var(--space-4);
}
.right {
  right: var(--space-4);
  width: 320px;
}
.overview {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
}
.ring {
  position: relative;
  flex: none;
  width: 104px;
  height: 104px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  box-shadow: 0 0 18px rgba(62, 224, 197, 0.18);
}
.ring > span {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: var(--twin-panel-strong);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 12px rgba(0, 0, 0, 0.6);
}
.ring b {
  font-size: 26px;
  line-height: 1.1;
  text-shadow: 0 0 10px var(--twin-glow);
}
.ring small,
.kpi span,
.kpi small {
  font-size: var(--fs-12);
  color: var(--twin-text-dim);
}
.kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.kpi b {
  font-size: 34px;
  line-height: 1.1;
}
.kpi b.alert {
  color: var(--state-early);
  text-shadow: 0 0 14px color-mix(in srgb, var(--state-early) 60%, transparent);
}
.total {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.total b {
  font-size: var(--fs-30);
  line-height: 1;
}
.total span {
  color: var(--twin-text-dim);
  font-size: var(--fs-13);
}
.states,
.lists,
.confirm {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.states li {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  align-items: center;
  column-gap: var(--space-2);
  font-size: var(--fs-13);
}
.states li .bar {
  grid-column: 1 / -1;
}
.bar {
  display: block;
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.bar em {
  display: block;
  height: 100%;
  background: currentColor;
  border-radius: 2px;
}
.st-healthy { color: var(--twin-healthy); }
.st-early { color: var(--state-early); }
.st-symptomatic { color: var(--twin-symptomatic); }
.st-unknown { color: var(--twin-unknown); }
.states li span:not(.bar),
.states li b {
  color: var(--twin-text);
}
.lists li {
  display: grid;
  grid-template-columns: 12px 1fr auto;
  align-items: center;
  column-gap: var(--space-2);
  font-size: var(--fs-13);
}
.lists li i {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--c);
}
.task-confirm { --c: var(--twin-confirm); }
.task-reshoot { --c: var(--twin-reshoot); }
.task-coverage { --c: var(--task-coverage); }
.task-random { --c: var(--task-random); }
.progress {
  margin: var(--space-3) 0 0;
  font-size: var(--fs-13);
  color: var(--twin-text-dim);
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
}
.progress .pct {
  font-size: var(--fs-20);
  color: var(--twin-accent);
  text-shadow: 0 0 10px var(--twin-glow);
}
.progress .bar {
  flex-basis: 100%;
}
.bar em {
  box-shadow: 0 0 8px currentColor;
}
.progress b {
  color: var(--twin-text);
}
.progress .bar {
  margin-top: 6px;
  color: var(--twin-accent);
}
.confirm button {
  width: 100%;
  appearance: none;
  border: 1px solid transparent;
  background: color-mix(in srgb, var(--twin-confirm) 14%, transparent);
  color: var(--twin-text);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  font: inherit;
  font-size: var(--fs-13);
  cursor: pointer;
  text-align: left;
}
.confirm button:hover {
  border-color: var(--twin-confirm);
}
.confirm span {
  color: var(--twin-text-dim);
  font-size: var(--fs-12);
}

.env-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2) var(--space-3);
}
.env-grid div {
  display: flex;
  flex-direction: column;
}
.env-grid span {
  font-size: var(--fs-12);
  color: var(--twin-text-dim);
}
.env-grid b {
  font-size: var(--fs-20);
}
.lv-high { color: var(--twin-symptomatic); }
.lv-mid { color: var(--state-early); }
.lv-low { color: var(--state-healthy); }
.lv-none { color: var(--twin-text-dim); font-size: var(--fs-14); }

.plant-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.plant-head h3 {
  margin: 0;
  font-size: var(--fs-20);
  color: var(--twin-text);
}
.x {
  appearance: none;
  border: none;
  background: none;
  color: var(--twin-text-dim);
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}
.plant-state {
  margin: var(--space-2) 0;
  font-size: var(--fs-16);
  font-weight: var(--fw-semibold);
}
.plant-state .dim {
  font-size: var(--fs-13);
  font-weight: var(--fw-regular);
}
.facts {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--fs-13);
}
.facts div {
  display: flex;
  justify-content: space-between;
}
.facts dt {
  color: var(--twin-text-dim);
}
.facts dd {
  margin: 0;
}
.why {
  margin-top: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-left: 3px solid var(--c);
  background: rgba(255, 255, 255, 0.04);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--fs-13);
}
.why span {
  color: var(--twin-text-dim);
}
.photos {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}
.photos figure {
  margin: 0;
}
.photos img {
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  border-radius: var(--radius-sm);
  border: 1px solid var(--twin-panel-border);
  display: block;
}
.photos figcaption {
  font-size: var(--fs-12);
  color: var(--twin-text-dim);
  margin-top: 2px;
}
.more {
  display: inline-block;
  margin-top: var(--space-3);
  color: var(--twin-accent);
  font-size: var(--fs-13);
  text-decoration: none;
}

/* 底栏 */
.bottom {
  left: var(--space-4);
  right: var(--space-4);
  bottom: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.rover-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 8px 14px;
  border-radius: 6px;
  background: var(--twin-panel);
  border: 1px solid var(--twin-panel-border);
  font-size: var(--fs-13);
  backdrop-filter: blur(8px);
  min-width: 320px;
}
.rover-line b {
  color: var(--twin-accent);
}
.pulse {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--twin-text-dim);
}
.pulse.moving,
.pulse.shooting {
  background: var(--twin-accent);
  animation: pulse 1.2s ease-in-out infinite;
}
.pulse.shooting {
  background: #fff;
}
@keyframes pulse {
  50% { box-shadow: 0 0 0 6px rgba(62, 224, 197, 0); opacity: 0.6; }
  0%, 100% { box-shadow: 0 0 0 0 rgba(62, 224, 197, 0.6); }
}
.legend {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--fs-12);
  color: var(--twin-text);
  padding: 8px 14px;
  border-radius: 6px;
  background: var(--twin-panel);
  border: 1px solid var(--twin-panel-border);
  backdrop-filter: blur(8px);
}
.legend i {
  font-style: normal;
  margin-right: 4px;
}
.legend em {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid var(--c);
  margin-right: 4px;
  vertical-align: -1px;
}
.legend > span:not(.sep) {
  color: var(--twin-text);
}
.legend > span.st-healthy i { color: var(--twin-healthy); }
.legend > span.st-early i { color: var(--state-early); }
.legend > span.st-symptomatic i { color: var(--twin-symptomatic); }
.legend > span.st-unknown i { color: var(--twin-unknown); }
.sep {
  width: 1px;
  height: 14px;
  background: var(--twin-panel-border);
}
.controls {
  margin-left: auto;
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  padding: 3px;
  border: 1px solid var(--twin-panel-border);
  border-radius: 6px;
  background: var(--twin-panel);
  backdrop-filter: blur(8px);
}
/* 工具条：按钮去掉各自的边框，合成一条 */
.controls button,
.controls .btn {
  border-color: transparent;
  background: transparent;
  border-radius: 4px;
  backdrop-filter: none;
}
.controls button:hover,
.controls .btn:hover {
  border-color: transparent;
  background: color-mix(in srgb, var(--twin-accent) 10%, transparent);
}
.controls button.on {
  border-color: transparent;
  background: color-mix(in srgb, var(--twin-accent) 18%, transparent);
  box-shadow: none;
}

.tip {
  position: fixed;
  z-index: 5;
  pointer-events: none;
  background: var(--twin-panel);
  border: 1px solid var(--twin-panel-border);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: var(--fs-12);
  display: flex;
  gap: var(--space-2);
  backdrop-filter: blur(8px);
}
.banner {
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  margin: 0;
  padding: var(--space-3) var(--space-5);
  background: var(--twin-panel);
  border: 1px solid var(--twin-panel-border);
  border-radius: var(--radius-lg);
}

.slide-enter-active,
.slide-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateX(12px);
}

@media (max-width: 900px) {
  .left { display: none; }
  .right { width: auto; left: var(--space-4); top: auto; bottom: 150px; max-height: 45vh; }
  .right .env { display: none; }
  .legend { display: none; }
  .brand-text small { display: none; }
}
</style>

<style>
/* CSS2DRenderer 的标签挂在场景容器里，不在组件作用域内 */
.twin-labels {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.twin-row-label {
  font-size: 11px;
  color: var(--twin-text-dim);
  background: rgba(10, 24, 26, 0.6);
  border: 1px solid var(--twin-panel-border);
  border-radius: 4px;
  padding: 1px 6px;
  white-space: nowrap;
}
.twin-rover-label {
  font-size: 11px;
  color: var(--twin-bg-top);
  background: var(--twin-accent);
  border-radius: 4px;
  padding: 1px 6px;
  font-weight: 600;
  white-space: nowrap;
  box-shadow: 0 0 10px rgba(62, 224, 197, 0.5);
}
</style>
