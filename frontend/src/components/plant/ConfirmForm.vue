<script setup lang="ts">
/**
 * 人工确认一株（计划 0015 的确认机制，计划 0018 阶段 B 加关任务）：四选一写成标注，挂在回看期内最近一张合格叶背图上，
 * 再把这株未完成的「确认」任务走到已完成。单株时间线和待确认面板共用；只读账号只显示说明。
 * compact：待确认面板底栏用，确认人和备注收起来，点开再填。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { EditPen } from '@element-plus/icons-vue'
import { confirmApi } from '../../api'
import { errMsg } from '../../api/http'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import { CONFIRM_OPTIONS, type AnnotationLabel, type RevisitTask, type TimelinePhoto } from '../../types'
import { fieldClock } from '../../utils/fieldTime'

const props = withDefaults(defineProps<{
  unitId: number
  fieldId: number
  target: TimelinePhoto | null
  /** 手里已有的这株未完成确认任务；不给就按地块查一次 */
  tasks?: RevisitTask[]
  /** 照片还在加载：先别提示「没有合格叶背」 */
  loading?: boolean
  compact?: boolean
}>(), { tasks: undefined, loading: false, compact: false })

const emit = defineEmits<{ done: [result: { label: AnnotationLabel; text: string; closed: number; failed: number }] }>()

const auth = useAuthStore()
const ui = useUiStore()

const label = ref<AnnotationLabel | ''>('')
const annotator = ref(auth.user?.display_name ?? '')
const note = ref('')
const submitting = ref(false)
const showExtra = ref(!props.compact)

// 换了一株就清掉上一株的选择和备注（确认人留着）
watch(() => props.unitId, () => {
  label.value = ''
  note.value = ''
})

const disabled = computed(() => props.target == null || submitting.value)
const hint = computed(() => {
  if (props.loading) return '正在取照片…'
  if (!props.target) return '回看期内没有合格的叶背图，先补拍叶背再确认'
  return `结论挂到 ${fieldClock(props.target.captured_at)} 的叶背图`
})

async function submit() {
  const target = props.target
  const value = label.value
  if (!target || !value) return
  const name = annotator.value.trim()
  if (!name) {
    showExtra.value = true
    ElMessage.warning('请填写确认人')
    return
  }
  const text = CONFIRM_OPTIONS.find((o) => o.label === value)?.text ?? value
  submitting.value = true
  try {
    const result = await confirmApi.confirmPlant({
      unitId: props.unitId, fieldId: props.fieldId, pointId: target.capture_point_id,
      label: value, labelText: text, annotator: name, note: note.value.trim() || null, tasks: props.tasks,
    })
    if (result.failed) {
      ElMessage.warning(`已确认为「${text}」，但有 ${result.failed} 条确认任务没关上，待确认里还会出现`)
    } else {
      ElMessage.success(result.closed ? `已确认为「${text}」，关闭了 ${result.closed} 条确认任务` : `已确认为「${text}」`)
    }
    label.value = ''
    note.value = ''
    void ui.refreshConfirmCount(true)
    emit('done', { label: value, text, ...result })
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <p v-if="auth.isViewer" class="readonly muted text-13">只读账号可以看照片和状态，确认由操作员或管理员提交。</p>
  <form v-else class="confirm-form" :class="{ compact }" @submit.prevent="submit">
    <div class="options" role="radiogroup" aria-label="确认结论">
      <button v-for="o in CONFIRM_OPTIONS" :key="o.label" type="button" role="radio" class="option"
              :class="[o.state ?? 'other', { on: label === o.label }]" :aria-checked="label === o.label"
              :disabled="disabled" @click="label = o.label">
        <i class="dot" aria-hidden="true" />{{ o.text }}
      </button>
    </div>

    <div v-if="showExtra" class="extra">
      <el-input v-model="annotator" placeholder="确认人" maxlength="50" class="who" :disabled="disabled">
        <template #prepend>确认人</template>
      </el-input>
      <el-input v-model="note" placeholder="备注（可选）" maxlength="200" class="note" :disabled="disabled" />
    </div>

    <div class="foot">
      <span class="hint">
        {{ hint }}
        <el-button v-if="!showExtra" link type="primary" size="small" :icon="EditPen" @click="showExtra = true">
          {{ annotator ? `确认人 ${annotator}` : '填确认人' }} · 加备注
        </el-button>
      </span>
      <span class="buttons">
        <slot name="extra" />
        <el-button type="primary" native-type="submit" :loading="submitting" :disabled="disabled || !label">提交确认</el-button>
      </span>
    </div>
  </form>
</template>

<style scoped>
.confirm-form { display: flex; flex-direction: column; gap: var(--space-3); }
.readonly { margin: 0; }
.options { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-2); }
.option {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 40px;
  padding: 0 var(--space-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--fs-14);
  cursor: pointer;
}
.option:hover:not(:disabled) { border-color: var(--brand-400); }
.option:disabled { cursor: not-allowed; color: var(--text-disabled); background: var(--bg-subtle); }
.option:focus-visible { outline: 2px solid var(--brand-600); outline-offset: 1px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--neutral-400); }
.healthy .dot { background: var(--state-healthy); }
.early .dot { background: var(--state-early); }
.symptomatic .dot { background: var(--state-symptomatic); }
/* 选中：加粗描边 + 浅底 + 粗体，灰度下靠描边和字重分辨 */
.option.on { border-width: 2px; font-weight: var(--fw-semibold); }
.option.on.healthy { border-color: var(--state-healthy); background: var(--state-healthy-soft); color: var(--state-healthy-ink); }
.option.on.early { border-color: var(--state-early); background: var(--state-early-soft); color: var(--state-early-ink); }
.option.on.symptomatic { border-color: var(--state-symptomatic); background: var(--state-symptomatic-soft); color: var(--state-symptomatic-ink); }
.option.on.other { border-color: var(--neutral-600); background: var(--neutral-100); }

.extra { display: grid; grid-template-columns: minmax(0, 220px) minmax(0, 1fr); gap: var(--space-2); }
.foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2) var(--space-3); }
.hint { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); font-size: var(--fs-13); color: var(--text-secondary); }
.buttons { display: inline-flex; gap: var(--space-2); margin-left: auto; }
.buttons :deep(.el-button + .el-button) { margin-left: 0; }

@media (max-width: 767px) {
  .options { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .compact .options { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
  .option { height: 44px; padding: 0 var(--space-1); gap: 6px; }
  .extra { grid-template-columns: minmax(0, 1fr); }
  .buttons { width: 100%; }
  .buttons > :deep(*) { flex: 1; }
}
</style>
