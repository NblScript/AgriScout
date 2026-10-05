<script setup lang="ts">
/**
 * 大棚详情 · 概览：大棚看「垄 × 株」状态网格、棚内环境近 72 小时、最近一次计划、等人确认；
 * 大田（小麦方法验证资产，D16 保留）看地块地图上最近一趟巡检的轨迹和采样点，以及最近巡检列表。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Camera, Sunrise } from '@element-plus/icons-vue'
import ConfirmPanel from '../../components/ConfirmPanel.vue'
import EnvPanel from '../../components/EnvPanel.vue'
import MapCanvas from '../../components/MapCanvas.vue'
import PlantGrid from '../../components/PlantGrid.vue'
import EmptyState from '../../components/ui/EmptyState.vue'
import SectionCard from '../../components/ui/SectionCard.vue'
import TaskTypeTag from '../../components/ui/TaskTypeTag.vue'
import { capturePointsApi, patrolsApi } from '../../api'
import { PLAN_LISTS, planProgress, statesUpdatedAt } from '../../composables/useGreenhouseBoard'
import { useFieldDetail } from '../../composables/useFieldDetail'
import { useAuthStore } from '../../stores/auth'
import { ANALYSIS_STATUS_LABELS, type CapturePointFull, type PatrolDetail } from '../../types'
import { fieldClock, fieldDate } from '../../utils/fieldTime'

const d = useFieldDetail()
const auth = useAuthStore()
const router = useRouter()
const now = ref(Date.now())

onMounted(() => {
  void d.patrols.load()
  if (d.greenhouse.value) {
    void d.env.load()
    void d.plan.load()
    void d.states.load()
    void d.confirm.load()
  }
})
// 页头「刷新」后，「读数截至 N 分钟前」也跟着按新时刻算
watch(() => d.env.data.value, () => { now.value = Date.now() })

/* ---------- 大棚 ---------- */
const plan = computed(() => d.plan.data.value)
const isToday = computed(() => plan.value?.plan_date === fieldDate())
const todayPlan = computed(() => (isToday.value ? plan.value : null))
const progress = computed(() => planProgress(plan.value))
const basisAt = computed(() => statesUpdatedAt(d.states.data.value))
const gridSubtitle = computed(() => basisAt.value == null
  ? '还没有巡检或人工确认，全部为不明'
  : `每株当前状态，依据截至 ${fieldClock(basisAt.value)} 的巡检和人工确认；描边是今日计划任务`)
const planSubtitle = computed(() => {
  const p = plan.value
  if (!p) return d.plan.error.value || '还没有生成过计划'
  return `${p.plan_date}${isToday.value ? '（今天）' : ''} · 第 ${p.generation ?? '—'} 次生成于 ${fieldClock(p.generated_at)}`
})
const planEnvText = computed(() => {
  const env = plan.value?.env
  if (!env) return ''
  return env.env_missing || env.env_index == null
    ? '生成时环境数据不足，补拍预算按中值排'
    : `生成时环境风险 ${env.env_index.toFixed(2)}`
})

/* ---------- 大田：最近一趟巡检的轨迹和采样点 ---------- */
const lastDetail = ref<PatrolDetail | null>(null)
const lastPoints = ref<CapturePointFull[]>([])
const mapLoading = ref(false)
watch(() => d.patrols.data.value.items[0]?.id, async (id) => {
  if (d.greenhouse.value || id == null || id === lastDetail.value?.id) return
  mapLoading.value = true
  try {
    const [detail, points] = await Promise.all([patrolsApi.get(id), capturePointsApi.listByPatrol(id)])
    lastDetail.value = detail
    lastPoints.value = points.items
  } catch { /* 地图只缺轨迹和点，边界照样画 */ } finally {
    mapLoading.value = false
  }
}, { immediate: true })
const recentPatrols = computed(() => d.patrols.data.value.items.slice(0, 8))

function statusType(status: string): 'success' | 'danger' | 'warning' | 'info' {
  return status === 'done' ? 'success' : status === 'error' ? 'danger' : status === 'running' ? 'warning' : 'info'
}
</script>

<template>
  <div v-if="d.greenhouse.value" class="overview">
    <div class="main">
      <SectionCard title="株状态" :subtitle="gridSubtitle">
        <template #actions>
          <span v-if="todayPlan && progress" class="muted text-13">
            今日计划 <b class="num">{{ progress.total }}</b> 株 · 已完成 <b class="num">{{ progress.done }}</b>
          </span>
        </template>
        <PlantGrid v-if="d.states.loaded.value" :states="d.states.data.value" :plan="todayPlan" :max-cell="40" />
        <el-skeleton v-else animated :rows="6" />
      </SectionCard>
      <ConfirmPanel :tasks="d.confirm.data.value" navigable :more-to="`/confirm?field_id=${d.fieldId}`" />
    </div>

    <div class="side">
      <EnvPanel :env="d.env.data.value" :now="now" />

      <SectionCard title="最近一次计划" :subtitle="planSubtitle">
        <template v-if="plan" #actions>
          <router-link :to="`/fields/${d.fieldId}/plan`" class="more">查看名单<el-icon><ArrowRight /></el-icon></router-link>
        </template>
        <div v-if="plan" class="plan">
          <el-tag v-if="!isToday" type="warning" effect="plain" size="small" class="not-today">不是今天的计划</el-tag>
          <div class="plan-lists">
            <TaskTypeTag v-for="name in PLAN_LISTS" :key="name" :type="name" long :count="plan[name].length" />
          </div>
          <div v-if="progress" class="progress">
            <span class="text-13">已完成 <b class="num">{{ progress.done }}</b> / {{ progress.total }} 株</span>
            <span class="meter" aria-hidden="true">
              <i :style="{ width: progress.total ? `${(progress.done / progress.total) * 100}%` : '0%' }" />
            </span>
          </div>
          <p class="line" :class="{ on: plan.window }">
            <el-icon><Sunrise /></el-icon>
            <template v-if="plan.window">叶背补拍建议 {{ plan.window.start }}–{{ plan.window.end }}</template>
            <template v-else>这一天没有清晨叶背窗口</template>
          </p>
          <p class="line">{{ planEnvText }}</p>
        </div>
        <EmptyState v-else-if="d.plan.loaded.value" compact title="还没有计划"
                    :description="auth.isViewer ? '由操作员或管理员在「巡检计划」里生成。' : '在「巡检计划」标签里选好日期生成。'">
          <el-button v-if="!auth.isViewer" size="small" type="primary" @click="router.push(`/fields/${d.fieldId}/plan`)">去生成</el-button>
        </EmptyState>
        <el-skeleton v-else animated :rows="3" />
      </SectionCard>
    </div>
  </div>

  <div v-else class="overview open">
    <SectionCard :title="lastDetail ? `最近一趟巡检 #${lastDetail.id}` : '地块地图'" class="map-card"
                 :subtitle="lastDetail ? `${fieldClock(lastDetail.started_at)} · ${lastDetail.point_count} 个采样点；点颜色为长势等级（1 差 → 5 旺），红圈为病害模型检出` : '地块边界'">
      <template v-if="lastDetail" #actions>
        <router-link :to="`/patrols/${lastDetail.id}`" class="more">打开回放<el-icon><ArrowRight /></el-icon></router-link>
      </template>
      <div v-loading="mapLoading" class="map">
        <MapCanvas v-if="d.field.data.value" :boundary="d.field.data.value.boundary" :track="lastDetail?.track ?? null"
                   :points="lastPoints" :selected-index="null" />
      </div>
    </SectionCard>

    <SectionCard title="最近巡检" :subtitle="d.patrols.data.value.total ? `共 ${d.patrols.data.value.total} 次` : ''" flush>
      <template v-if="d.patrols.data.value.total > recentPatrols.length" #actions>
        <router-link :to="`/fields/${d.fieldId}/patrols`" class="more">全部<el-icon><ArrowRight /></el-icon></router-link>
      </template>
      <ul v-if="recentPatrols.length" class="patrol-list">
        <li v-for="p in recentPatrols" :key="p.id">
          <router-link :to="`/patrols/${p.id}`" class="patrol-row">
            <span class="patrol-main">
              <b>#{{ p.id }} · {{ fieldClock(p.started_at) }}</b>
              <span class="muted text-12">{{ p.device_code ?? '未登记设备' }}</span>
            </span>
            <el-tag size="small" effect="plain" :type="statusType(p.analysis_status)">
              {{ ANALYSIS_STATUS_LABELS[p.analysis_status] ?? p.analysis_status }}
            </el-tag>
          </router-link>
        </li>
      </ul>
      <EmptyState v-else-if="d.patrols.loaded.value" compact :icon="Camera" title="还没有巡检" description="小车上传巡检包后在这里出现" />
    </SectionCard>
  </div>
</template>

<style scoped>
.overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 400px);
  align-items: start;
  gap: var(--space-4);
}
.overview.open { grid-template-columns: minmax(0, 1fr) minmax(280px, 360px); }
.main, .side { display: flex; flex-direction: column; gap: var(--space-4); min-width: 0; }
.more { display: inline-flex; align-items: center; gap: 2px; font-size: var(--fs-13); }
.num { font-variant-numeric: tabular-nums; color: var(--text-primary); font-weight: var(--fw-medium); }

.plan { display: flex; flex-direction: column; gap: var(--space-3); }
.not-today { align-self: flex-start; }
.plan-lists { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.progress { display: flex; align-items: center; gap: var(--space-3); }
.progress .text-13 { white-space: nowrap; color: var(--text-secondary); }
.meter { flex: 1; height: 6px; border-radius: 3px; background: var(--neutral-200); overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--brand-600); border-radius: 3px; }
.line { display: flex; align-items: center; gap: var(--space-1); margin: 0; font-size: var(--fs-13); line-height: var(--lh-13); color: var(--text-secondary); }
.line.on { color: var(--warning-ink); }

.map { height: 460px; border-radius: var(--radius-md); overflow: hidden; }
.patrol-list { list-style: none; margin: 0; padding: 0; }
.patrol-list li + li { border-top: 1px solid var(--border); }
.patrol-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  color: var(--text-primary);
}
.patrol-row:hover { background: var(--bg-hover); }
.patrol-main { display: flex; flex-direction: column; min-width: 0; }
.patrol-main b { font-weight: var(--fw-medium); font-size: var(--fs-14); font-variant-numeric: tabular-nums; }

@media (max-width: 1279px) {
  .overview, .overview.open { grid-template-columns: minmax(0, 1fr); }
  .side { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); align-items: start; }
}
@media (max-width: 767px) {
  .map { height: 320px; }
  .side { display: flex; }
}
</style>
