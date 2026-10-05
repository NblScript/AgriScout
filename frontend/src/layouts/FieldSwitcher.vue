<script setup lang="ts">
/**
 * 顶栏地块切换器（计划 0018 设计 3）：记住上次选择（localStorage，读写包 try/catch，在 ui store 里）。
 * 在大棚详情的某个标签页上切换时留在同一标签（目标是大田而它没有这个标签时进概览）；其余页面切换即进入该地块的详情页。
 */
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, Check, MapLocation } from '@element-plus/icons-vue'
import { useFieldsStore } from '../stores/fields'
import { useUiStore } from '../stores/ui'
import { FACILITY_LABELS, isGreenhouse, type Field } from '../types'
import { fieldHomePath } from './nav'

const fields = useFieldsStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const groups = computed(() => [
  { label: '大棚', items: fields.list.filter((f) => isGreenhouse(f)) },
  { label: '大田', items: fields.list.filter((f) => !isGreenhouse(f)) },
].filter((g) => g.items.length))
const current = computed<Field | undefined>(() =>
  ui.currentFieldId == null ? undefined : fields.byId.get(ui.currentFieldId))

/** 记住的地块已被删除或从未选过：默认第一个大棚 */
function ensureValid() {
  if (!fields.loaded || current.value) return
  const fallback = fields.list.find((f) => isGreenhouse(f)) ?? fields.list[0]
  ui.setCurrentField(fallback?.id ?? null)
}

onMounted(() => {
  fields.load().then(ensureValid).catch(() => { /* 拿不到地块时切换器为空，不挡页面 */ })
})
watch(() => fields.list, ensureValid)

// 进了某个地块的子页，切换器跟着显示这个地块
watch(() => [route.meta.fieldScoped, route.params.id] as const, ([scoped, id]) => {
  const n = Number(id)
  if (scoped && Number.isInteger(n) && n > 0) ui.setCurrentField(n)
}, { immediate: true })

/** 大田的详情页只有这两个标签 */
const OPEN_FIELD_TABS = new Set(['field-detail', 'field-patrols'])

function pick(id: number) {
  const field = fields.byId.get(id)
  if (!field) return
  ui.setCurrentField(id)
  if (route.meta.fieldScoped && route.name && (isGreenhouse(field) || OPEN_FIELD_TABS.has(String(route.name)))) {
    void router.push({ name: route.name, params: { ...route.params, id }, query: route.query })
    return
  }
  void router.push(fieldHomePath(field))
}

function facility(field: Field): string {
  return FACILITY_LABELS[field.facility_type ?? 'open_field']
}
</script>

<template>
  <el-dropdown trigger="click" placement="bottom-end" :disabled="!fields.list.length" @command="pick">
    <button class="switcher" type="button" aria-label="切换地块">
      <el-icon class="lead"><MapLocation /></el-icon>
      <span class="name">{{ current?.name ?? (fields.loaded ? '暂无地块' : '加载地块…') }}</span>
      <el-icon class="caret"><ArrowDown /></el-icon>
    </button>
    <template #dropdown>
      <el-dropdown-menu class="field-menu">
        <template v-for="group in groups" :key="group.label">
          <li class="group-label" role="presentation">{{ group.label }}</li>
          <el-dropdown-item v-for="f in group.items" :key="f.id" :command="f.id">
            <span class="item">
              <el-icon class="check" :class="{ on: f.id === current?.id }"><Check /></el-icon>
              <span class="item-name">{{ f.name }}</span>
              <span class="item-type">{{ facility(f) }}</span>
            </span>
          </el-dropdown-item>
        </template>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.switcher {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 32px;
  max-width: 260px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--fs-13);
  cursor: pointer;
}
.switcher:hover { border-color: var(--neutral-400); }
.switcher:focus-visible { outline: 2px solid var(--brand-300); outline-offset: 1px; }
.lead { color: var(--brand-600); flex: none; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.caret { color: var(--text-secondary); flex: none; }
.group-label {
  list-style: none;
  padding: var(--space-2) var(--space-4) var(--space-1);
  font-size: var(--fs-12);
  color: var(--text-secondary);
}
.item { display: flex; align-items: center; gap: var(--space-2); min-width: 220px; }
.check { visibility: hidden; color: var(--brand-600); }
.check.on { visibility: visible; }
.item-name { flex: 1; }
.item-type { font-size: var(--fs-12); color: var(--text-secondary); }
</style>
