<script setup lang="ts">
/**
 * 大棚详情（计划 0018 阶段 B）：一个地块一页，标签页是子路由——
 * 大棚：概览 / 巡检计划 / 株档案 / 环境 / 巡检记录；大田只有概览（地图 + 最近巡检）和巡检记录。
 * 0014/0015 的旧地址 /fields/:id/units、/fields/:id/plan 就是这里的子路由，已有链接不失效。
 * 各标签共用的数据在 useFieldDetail 里，切标签不重复请求。
 */
import { computed, onMounted, watch, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MapLocation, Monitor, Refresh } from '@element-plus/icons-vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import { useBreadcrumb } from '../composables/useBreadcrumb'
import { provideFieldDetail } from '../composables/useFieldDetail'
import { FACILITY_LABELS } from '../types'
import { fieldClock, relativeTime } from '../utils/fieldTime'

const route = useRoute()
const router = useRouter()
const fieldId = Number(route.params.id)
const valid = Number.isInteger(fieldId) && fieldId > 0
const detail = provideFieldDetail(valid ? fieldId : 0)
const { field, states, patrols, greenhouse, refreshing } = detail

interface Tab {
  name: string
  label: string
  path: string
  greenhouseOnly?: boolean
}
const TABS: Tab[] = [
  { name: 'field-detail', label: '概览', path: '' },
  { name: 'field-plan', label: '巡检计划', path: '/plan', greenhouseOnly: true },
  { name: 'field-units', label: '株档案', path: '/units', greenhouseOnly: true },
  { name: 'field-env', label: '环境', path: '/env', greenhouseOnly: true },
  { name: 'field-patrols', label: '巡检记录', path: '/patrols' },
]
/** 大田只列概览和巡检记录；从旧链接直接打开大田的株档案等子页时，当前这一页也列出来 */
const tabs = computed(() => TABS.filter((t) => greenhouse.value || !t.greenhouseOnly || t.name === route.name))
const current = computed(() => TABS.find((t) => t.name === route.name) ?? TABS[0])
const name = computed(() => field.data.value?.name ?? `地块 #${fieldId}`)
const lastPatrol = computed(() => patrols.data.value.items[0] ?? null)

function tabCount(tab: Tab): number | null {
  if (tab.name === 'field-units' && states.loaded.value) return states.data.value.length
  if (tab.name === 'field-patrols' && patrols.loaded.value) return patrols.data.value.total
  return null
}

useBreadcrumb(() => current.value.name === 'field-detail'
  ? [{ label: '大棚与地块', to: '/fields' }, { label: name.value }]
  : [{ label: '大棚与地块', to: '/fields' }, { label: name.value, to: `/fields/${fieldId}` }, { label: current.value.label }])

// 标签页标题带上地块名（路由守卫只知道「大棚详情」这类通用标题）
watchEffect(() => {
  if (field.data.value) document.title = `${current.value.label === '概览' ? '' : `${current.value.label} · `}${name.value} · 巡知`
})

onMounted(() => {
  if (!valid) {
    void router.replace({ name: 'fields' })
    return
  }
  void field.load()
  void patrols.load()
})
// 大棚才有每株状态；地块信息到了再拉，株档案标签的计数也靠它
watch(greenhouse, (yes) => { if (yes) void states.load() }, { immediate: true })
</script>

<template>
  <PageHeader :title="name">
    <template #meta>
      <template v-if="field.data.value">
        <el-tag size="small" effect="plain" :type="greenhouse ? 'primary' : 'info'">
          {{ FACILITY_LABELS[field.data.value.facility_type ?? 'open_field'] }}
        </el-tag>
        <span v-if="greenhouse && states.loaded.value" class="meta-text">在册 <b>{{ states.data.value.length }}</b> 株</span>
        <span v-if="field.data.value.area_ha != null" class="meta-text">{{ field.data.value.area_ha }} 公顷</span>
        <span class="meta-text">
          <template v-if="lastPatrol">
            最近巡检
            <router-link :to="`/patrols/${lastPatrol.id}`">#{{ lastPatrol.id }}</router-link>
            · {{ fieldClock(lastPatrol.started_at) }}（{{ relativeTime(lastPatrol.started_at) }}）
          </template>
          <template v-else-if="patrols.loaded.value">还没有巡检</template>
        </span>
      </template>
    </template>
    <template #actions>
      <el-button v-if="greenhouse" :icon="Monitor" @click="router.push(`/screen?field=${fieldId}`)">展示屏</el-button>
      <el-button :icon="Refresh" :loading="refreshing" @click="detail.refresh()">刷新</el-button>
    </template>
    <nav v-if="field.data.value" class="tabs" aria-label="大棚详情标签页">
      <router-link v-for="tab in tabs" :key="tab.name" :to="`/fields/${fieldId}${tab.path}`" class="tab"
                   :class="{ active: tab.name === current.name }" :aria-current="tab.name === current.name ? 'page' : undefined">
        {{ tab.label }}<span v-if="tabCount(tab) != null" class="tab-count">{{ tabCount(tab) }}</span>
      </router-link>
    </nav>
  </PageHeader>

  <router-view v-if="field.data.value" />
  <el-skeleton v-else-if="!field.loaded.value" animated :rows="8" />
  <EmptyState v-else :icon="MapLocation" :title="field.error.value || '没有找到这个地块'" description="地块可能已被删除。">
    <el-button type="primary" @click="router.push('/fields')">回到大棚与地块</el-button>
  </EmptyState>
</template>

<style scoped>
.meta-text { font-size: var(--fs-13); color: var(--text-secondary); }
.meta-text b { color: var(--text-primary); font-variant-numeric: tabular-nums; font-weight: var(--fw-medium); }
.tabs {
  display: flex;
  gap: var(--space-5);
  margin-top: var(--space-4);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
}
.tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-2) 0 var(--space-3);
  font-size: var(--fs-14);
  line-height: var(--lh-14);
  color: var(--text-secondary);
  white-space: nowrap;
}
.tab:hover { color: var(--text-primary); }
.tab.active { color: var(--brand-700); font-weight: var(--fw-medium); }
.tab.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  border-radius: 1px;
  background: var(--brand-600);
}
.tab-count {
  min-width: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: var(--neutral-100);
  font-size: var(--fs-12);
  line-height: 18px;
  text-align: center;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  font-weight: var(--fw-regular);
}
.tab.active .tab-count { background: var(--brand-50); color: var(--brand-700); }
.tab:focus-visible { outline: 2px solid var(--brand-300); outline-offset: 2px; border-radius: 2px; }
@media (max-width: 767px) {
  .tabs { gap: var(--space-4); }
}
</style>
