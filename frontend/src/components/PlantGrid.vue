<script setup lang="ts">
/**
 * 「垄 × 株」状态网格（计划 0018 设计 6）：行 = 垄，列 = 株序号；解析不出垄号的株排在末尾「未编号」行。
 * 格子填株状态色（「不明」另加斜线底纹）；今日计划里有任务的格子加任务类型色描边（确认实线、补拍虚线、全覆盖点线、抽查双线）；
 * 上次叶背不合格的加白色角标；格子够大时异常状态另画形状。悬停看株号、状态、原因，点击进单株时间线；图例兼作筛选。
 * 巡检回放（阶段 B）另传 visited（本次巡到的株，其余淡显）和 selected（正在看的株，加深色框），点击改为发 pick 事件。
 * 渲染用一个 CSS Grid（一株一个元素，3000 株实测见计划 0018）；fit="both" 时按容器宽高算格子边长，放不下就在组件内滚动。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PlantGridTip from './PlantGridTip.vue'
import StateTag from './ui/StateTag.vue'
import TaskTypeTag from './ui/TaskTypeTag.vue'
import type { PatrolPlan, PlanItem, PlanListName, PlantState, PlantStateValue } from '../types'

const props = withDefaults(defineProps<{
  states: PlantState[]
  /** 今日计划；为空时不画任务描边 */
  plan?: PatrolPlan | null
  /** width：只按宽度定格子大小（高度随内容）；both：按容器宽高放进去（容器须有确定高度） */
  fit?: 'width' | 'both'
  maxCell?: number
  minCell?: number
  navigable?: boolean
  /** 只突出这些株（巡检回放：本次巡到的株）；为空时全部正常显示 */
  visited?: ReadonlySet<number> | null
  /** 加深色框的株（巡检回放：正在看的株） */
  selected?: number | null
}>(), { plan: null, fit: 'width', maxCell: 28, minCell: 6, navigable: true, visited: null, selected: null })
const emit = defineEmits<{ pick: [unitId: number] }>()

const STATES: PlantStateValue[] = ['healthy', 'early', 'symptomatic', 'unknown']
const LISTS: PlanListName[] = ['confirm', 'reshoot', 'coverage', 'random']
const LABEL_WIDTH = 44
const HEADER_HEIGHT = 18

interface Cell {
  index: number
  plant: PlantState
  line: number
  col: number
  task: PlanItem | null
  underBad: boolean
  /** 「grid-area: 行 / 列」，布局时拼好，渲染时不再逐格建样式对象 */
  area: string
}

/* ---------- 布局：垄 → 行，株序号 → 列 ---------- */
const tasksByUnit = computed(() => {
  const map = new Map<number, PlanItem>()
  if (!props.plan) return map
  for (const list of LISTS) {
    for (const item of props.plan[list]) {
      if (item.task_status !== 'cancelled' && !map.has(item.unit_id)) map.set(item.unit_id, item)
    }
  }
  return map
})

const layout = computed(() => {
  const numbered = props.states.filter((s) => s.row_no != null && s.position_no != null)
  const loose = props.states.filter((s) => s.row_no == null || s.position_no == null)
  const rowNos = [...new Set(numbered.map((s) => s.row_no as number))].sort((a, b) => a - b)
  const maxSeq = numbered.reduce((max, s) => Math.max(max, s.position_no as number), 0)
  const cols = Math.max(maxSeq, Math.min(loose.length, 30), 1)
  const lineOfRow = new Map(rowNos.map((row, i) => [row, i + 1]))
  const lines = rowNos.map((row) => `${row} 垄`)
  const cells: Cell[] = []
  const push = (plant: PlantState, line: number, col: number) => {
    const task = tasksByUnit.value.get(plant.unit_id) ?? null
    cells.push({ index: cells.length, plant, line, col, task, underBad: plant.last_under_accepted === false, area: `grid-area:${line + 1}/${col + 1}` })
  }
  for (const plant of numbered) push(plant, lineOfRow.get(plant.row_no as number)!, plant.position_no as number)
  // 未编号的株按株号排，满一行换行；只有第一行写「未编号」
  const sortedLoose = [...loose].sort((a, b) => a.key.localeCompare(b.key))
  sortedLoose.forEach((plant, i) => {
    const line = rowNos.length + 1 + Math.floor(i / cols)
    if (i % cols === 0) lines.push(i === 0 ? '未编号' : '')
    push(plant, line, (i % cols) + 1)
  })
  return { cells, lines, cols }
})

/* ---------- 格子尺寸 ---------- */
const host = ref<HTMLElement>()
const cell = ref(props.maxCell)
const gap = computed(() => (cell.value >= 16 ? 4 : cell.value >= 9 ? 2 : 1))
let observer: ResizeObserver | null = null

function measure() {
  const el = host.value
  if (!el) return
  const { cols, lines } = layout.value
  const byWidth = (el.clientWidth - LABEL_WIDTH) / cols
  const byHeight = props.fit === 'both' ? (el.clientHeight - HEADER_HEIGHT) / Math.max(lines.length, 1) : Infinity
  const raw = Math.min(byWidth, byHeight)
  const g = raw >= 20 ? 4 : raw >= 11 ? 2 : 1
  cell.value = Math.max(props.minCell, Math.min(props.maxCell, Math.floor(raw - g)))
}
/** 首次量好容器尺寸后才渲染格子 */
const measured = ref(false)
onMounted(() => {
  measure()
  measured.value = true
  observer = new ResizeObserver(() => measure())
  if (host.value) observer.observe(host.value)
})
onBeforeUnmount(() => observer?.disconnect())
watch(() => [layout.value.cols, layout.value.lines.length, props.fit], () => measure())

/** 列号：格子大时每列都标，小了隔 5 或 10 列标一个 */
const colLabels = computed(() => {
  const step = cell.value >= 22 ? 1 : cell.value >= 12 ? 5 : 10
  const labels: number[] = []
  for (let c = 1; c <= layout.value.cols; c += 1) if (c === 1 || c % step === 0) labels.push(c)
  return labels
})
/** 垄号：行高放不下一行字时隔 5 行标一个（「未编号」总是标） */
const rowLabels = computed(() => {
  const step = cell.value + gap.value >= 16 ? 1 : 5
  return layout.value.lines
    .map((label, i) => ({ label, line: i + 1 }))
    .filter(({ label, line }) => label && (step === 1 || line === 1 || line % step === 0 || label === '未编号'))
})

/* ---------- 图例与筛选 ---------- */
type Filter = { kind: 'state'; value: PlantStateValue } | { kind: 'task'; value: PlanListName } | { kind: 'under' }
const filter = ref<Filter | null>(null)
const counts = computed(() => {
  const state: Record<PlantStateValue, number> = { healthy: 0, early: 0, symptomatic: 0, unknown: 0 }
  const task: Record<PlanListName, number> = { confirm: 0, reshoot: 0, coverage: 0, random: 0 }
  let under = 0
  for (const c of layout.value.cells) {
    state[c.plant.state] += 1
    if (c.task) task[c.task.list_name] += 1
    if (c.underBad) under += 1
  }
  return { state, task, under }
})
function isActive(f: Filter): boolean {
  const cur = filter.value
  if (!cur || cur.kind !== f.kind) return false
  return cur.kind === 'under' || (cur as { value: string }).value === (f as { value: string }).value
}
function toggle(f: Filter) {
  filter.value = isActive(f) ? null : f
}
function matches(c: Cell): boolean {
  const f = filter.value
  if (!f) return true
  if (f.kind === 'state') return c.plant.state === f.value
  if (f.kind === 'task') return c.task?.list_name === f.value
  return c.underBad
}

function cellClass(c: Cell): string {
  let cls = `pg-cell s-${c.plant.state}`
  if (c.task) cls += ` tk t-${c.task.list_name}`
  if (c.underBad) cls += ' u-bad'
  if (props.visited && !props.visited.has(c.plant.unit_id)) cls += ' nv'
  if (c.plant.unit_id === props.selected) cls += ' sel'
  if (!matches(c)) cls += ' dim'
  return cls
}

const visitedCount = computed(() => (props.visited ? layout.value.cells.filter((c) => props.visited!.has(c.plant.unit_id)).length : 0))

const summary = computed(() => {
  const s = counts.value.state
  return `垄 × 株状态网格，共 ${layout.value.cells.length} 株：健康 ${s.healthy}、早期 ${s.early}、明显 ${s.symptomatic}、不明 ${s.unknown}`
})

/* ---------- 悬停提示与点击 ---------- */
const hover = ref<{ cell: Cell; x: number; y: number; below: boolean } | null>(null)
function cellAt(event: Event): Cell | null {
  const target = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-i]')
  if (!target) return null
  return layout.value.cells[Number(target.dataset.i)] ?? null
}
function onOver(event: MouseEvent) {
  const c = cellAt(event)
  if (!c) { hover.value = null; return }
  const rect = (event.target as HTMLElement).getBoundingClientRect()
  const x = Math.min(Math.max(rect.left + rect.width / 2, 150), window.innerWidth - 150)
  const below = rect.top < 200
  hover.value = { cell: c, x, y: below ? rect.bottom + 8 : rect.top - 8, below }
}
const router = useRouter()
function onClick(event: MouseEvent) {
  const c = cellAt(event)
  if (!c) return
  emit('pick', c.plant.unit_id)
  if (props.navigable) void router.push(`/units/${c.plant.unit_id}`)
}
</script>

<template>
  <div class="plant-grid">
    <div ref="host" class="pg-viewport" :class="{ fill: fit === 'both' }">
      <div v-if="layout.cells.length && measured" class="pg-grid" role="img" :aria-label="summary"
           :style="{ '--cell': `${cell}px`, '--gap': `${gap}px`, '--cols': layout.cols, '--label': `${LABEL_WIDTH}px` }"
           :class="{ small: cell < 12, glyphs: cell >= 20, navigable }"
           @mouseover="onOver" @mouseleave="hover = null" @click="onClick">
        <span v-for="c in colLabels" :key="`c${c}`" class="pg-col-label" :style="{ gridColumn: c + 1 }">{{ c }}</span>
        <span v-for="row in rowLabels" :key="`l${row.line}`" class="pg-row-label" :style="{ gridRow: row.line + 1 }">{{ row.label }}</span>
        <!-- v-memo：悬停、换格子尺寸时不重建 3000 个格子，只有布局或筛选变了才重渲染 -->
        <i v-for="c in layout.cells" :key="c.plant.unit_id" v-memo="[c, filter, visited, c.plant.unit_id === selected]" :class="cellClass(c)" :data-i="c.index"
           :style="c.area" />
      </div>
      <p v-else-if="!layout.cells.length" class="pg-empty">还没有株档案</p>
    </div>

    <div class="pg-legend" aria-label="图例与筛选">
      <span class="pg-legend-group">
        <button v-for="s in STATES" :key="s" type="button" class="pg-chip" :class="{ on: isActive({ kind: 'state', value: s }) }"
                :aria-pressed="isActive({ kind: 'state', value: s })" @click="toggle({ kind: 'state', value: s })">
          <StateTag :state="s" size="small" /><b>{{ counts.state[s] }}</b>
        </button>
      </span>
      <span v-if="visited" class="pg-legend-group">
        <span class="pg-visited"><i class="pg-visited-swatch" aria-hidden="true" />本次巡到 <b>{{ visitedCount }}</b> 株，其余淡显</span>
      </span>
      <span v-if="plan" class="pg-legend-group">
        <span class="pg-legend-title">今日任务</span>
        <button v-for="t in LISTS" :key="t" type="button" class="pg-chip" :class="{ on: isActive({ kind: 'task', value: t }) }"
                :aria-pressed="isActive({ kind: 'task', value: t })" @click="toggle({ kind: 'task', value: t })">
          <TaskTypeTag :type="t" :count="counts.task[t]" />
        </button>
      </span>
      <button type="button" class="pg-chip" :class="{ on: isActive({ kind: 'under' }) }"
              :aria-pressed="isActive({ kind: 'under' })" @click="toggle({ kind: 'under' })">
        <span class="pg-under-tag"><i class="pg-under-swatch" aria-hidden="true" />叶背不合格</span><b>{{ counts.under }}</b>
      </button>
      <button v-if="filter" type="button" class="pg-clear" @click="filter = null">清除筛选</button>
    </div>

    <PlantGridTip v-if="hover" :plant="hover.cell.plant" :task="hover.cell.task" :x="hover.x" :y="hover.y"
                  :below="hover.below" :navigable="navigable" />
  </div>
</template>

<style scoped>
.plant-grid { display: flex; flex-direction: column; gap: var(--space-3); min-width: 0; min-height: 0; }
.pg-viewport { min-width: 0; overflow: auto; }
/* 填满容器时上下左右居中；用 margin:auto 而不是 align-items，放不下时还能滚到顶端 */
.pg-viewport.fill { flex: 1; min-height: 0; display: flex; }
.pg-viewport.fill .pg-grid { margin: auto; }
.pg-grid {
  display: grid;
  grid-template-columns: var(--label) repeat(var(--cols), var(--cell));
  grid-template-rows: 18px;
  grid-auto-rows: var(--cell);
  gap: var(--gap);
  width: max-content;
  margin: 0 auto;
}
.pg-col-label, .pg-row-label {
  font-size: var(--fs-12);
  line-height: 18px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.pg-col-label { grid-row: 1; justify-self: center; overflow: visible; }
.pg-row-label { grid-column: 1; align-self: center; text-align: right; padding-right: var(--space-2); }
.pg-cell {
  position: relative;
  display: block;
  border-radius: 2px;
  background: var(--state-healthy);
}
.navigable .pg-cell { cursor: pointer; }
.pg-cell:hover { box-shadow: 0 0 0 2px var(--neutral-900); z-index: 1; }
.s-early { background: var(--state-early); }
.s-symptomatic { background: var(--state-symptomatic); }
.s-unknown {
  background: repeating-linear-gradient(135deg, var(--state-unknown) 0 3px, var(--neutral-100) 3px 5px);
  box-shadow: inset 0 0 0 1px var(--neutral-300);
}
/* 今日任务：任务色描边 + 线型（与 TaskTypeTag、登录页示意一致） */
.tk { outline-offset: 1px; }
.t-confirm { outline: 2px var(--task-confirm-line) var(--task-confirm); }
.t-reshoot { outline: 2px var(--task-reshoot-line) var(--task-reshoot); }
.t-coverage { outline: 2px var(--task-coverage-line) var(--task-coverage); }
.t-random { outline: 3px var(--task-random-line) var(--task-random); }
.small .tk { outline-width: 1px; outline-offset: 0; }
/* 上次叶背不合格：右上角白点 + 深色圈，在四种底色上都看得见 */
.u-bad::after {
  content: '';
  position: absolute;
  top: 1px;
  right: 1px;
  width: max(4px, calc(var(--cell) * 0.32));
  height: max(4px, calc(var(--cell) * 0.32));
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 0 1px var(--neutral-900);
}
/* 格子够大时异常状态再画形状（▲ 早期、■ 明显、○ 不明），投影和灰度下不只靠颜色；健康不画，保持干净 */
.glyphs .s-early::before, .glyphs .s-symptomatic::before, .glyphs .s-unknown::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
}
.glyphs .s-early::before { width: 38%; height: 34%; clip-path: polygon(50% 0, 100% 100%, 0 100%); background: var(--state-early-ink); }
.glyphs .s-symptomatic::before { width: 28%; height: 28%; background: #fff; }
.glyphs .s-unknown::before { width: 30%; height: 30%; border-radius: 50%; box-shadow: 0 0 0 2px var(--neutral-500); }
.nv { opacity: 0.28; }
.sel { box-shadow: 0 0 0 2px var(--bg-card), 0 0 0 4px var(--neutral-900); z-index: 2; }
.dim { opacity: 0.16; outline-color: transparent; }
.pg-empty { margin: 0; padding: var(--space-5); text-align: center; color: var(--text-secondary); font-size: var(--fs-13); }

.pg-legend { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-4); }
.pg-legend-group { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); }
.pg-legend-title { font-size: var(--fs-12); color: var(--text-secondary); margin-right: var(--space-1); }
.pg-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: none;
  font: inherit;
  font-size: var(--fs-13);
  color: var(--text-primary);
  cursor: pointer;
}
.pg-chip b { font-weight: var(--fw-semibold); font-variant-numeric: tabular-nums; padding-right: 4px; }
.pg-chip:hover { background: var(--bg-subtle); }
.pg-chip.on { border-color: var(--neutral-700); background: var(--bg-card); }
.pg-chip:focus-visible { outline: 2px solid var(--brand-300); outline-offset: 1px; }
.pg-under-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--neutral-100);
  color: var(--text-regular);
  font-size: var(--fs-12);
  font-weight: var(--fw-medium);
}
.pg-under-swatch {
  position: relative;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  background: var(--state-healthy);
}
.pg-under-swatch::after {
  content: '';
  position: absolute;
  top: 1px;
  right: 1px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 0 1px var(--neutral-900);
}
.pg-visited { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-12); color: var(--text-secondary); }
.pg-visited b { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.pg-visited-swatch { width: 12px; height: 12px; border-radius: 2px; background: var(--state-healthy); }
.pg-clear {
  border: none;
  background: none;
  padding: 0;
  font: inherit;
  font-size: var(--fs-13);
  color: var(--brand-700);
  cursor: pointer;
}
.pg-clear:hover { text-decoration: underline; }
</style>
