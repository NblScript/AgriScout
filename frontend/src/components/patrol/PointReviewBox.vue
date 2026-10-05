<script setup lang="ts">
/**
 * 采样点的人工复核（回流闭环）：已有结论 + 提交表单，结论进入训练数据集。
 * 切点时防抖再取，旧点的响应不覆盖新点；提交在途时切了点，结果不串到新点。只读账号只看不改。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { annotationsApi } from '../../api'
import { errMsg } from '../../api/http'
import { useAuthStore } from '../../stores/auth'
import { ANNOTATION_LABELS, ANNOTATION_TAG_TYPES, type Annotation, type AnnotationLabel } from '../../types'

const props = defineProps<{ pointId: number }>()
const emit = defineEmits<{ changed: [] }>()

const ANNOTATOR_KEY = 'agriscout_annotator'
const auth = useAuthStore()
const annotations = ref<Annotation[]>([])
const label = ref<AnnotationLabel>('normal')
const note = ref('')
const annotator = ref(auth.user?.display_name ?? readAnnotator())
const submitting = ref(false)
let token = 0
let debounce: ReturnType<typeof setTimeout> | null = null

function readAnnotator(): string {
  try { return localStorage.getItem(ANNOTATOR_KEY) ?? '' } catch { return '' }
}

async function load(pointId: number) {
  const mine = ++token
  try {
    const rows = await annotationsApi.listByPoint(pointId)
    if (mine === token) annotations.value = rows
  } catch { /* 非关键，不打断回放 */ }
}
watch(() => props.pointId, (id) => {
  annotations.value = []
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => load(id), 250)
}, { immediate: true })
onBeforeUnmount(() => { if (debounce) clearTimeout(debounce) })

async function submit() {
  const pointId = props.pointId
  const name = annotator.value.trim()
  if (!name) {
    ElMessage.warning('请先填写标注人姓名（将作为数据集归属）')
    return
  }
  submitting.value = true
  try { localStorage.setItem(ANNOTATOR_KEY, name) } catch { /* 记不住名字不影响提交 */ }
  try {
    const saved = await annotationsApi.submit(pointId, { label: label.value, annotator_name: name, note: note.value.trim() || null })
    emit('changed')
    if (props.pointId !== pointId) return
    const idx = annotations.value.findIndex((a) => a.id === saved.id)
    if (idx >= 0) annotations.value[idx] = saved
    else annotations.value.push(saved)
    ElMessage.success(idx >= 0 ? '该标签已更新复核结论' : '复核结果已入库')
    note.value = ''
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    submitting.value = false
  }
}

async function remove(ann: Annotation) {
  try {
    await annotationsApi.remove(ann.id)
    annotations.value = annotations.value.filter((a) => a.id !== ann.id)
    emit('changed')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
</script>

<template>
  <div class="review">
    <h5>人工复核 <span class="muted">结论进入训练数据集</span></h5>
    <div v-if="annotations.length" class="tags">
      <el-tag v-for="a in annotations" :key="a.id" :type="ANNOTATION_TAG_TYPES[a.label as AnnotationLabel] ?? 'info'"
              :closable="!auth.isViewer" @close="remove(a)">
        {{ ANNOTATION_LABELS[a.label as AnnotationLabel] ?? a.label }} · {{ a.annotator_name }}
      </el-tag>
    </div>
    <p v-else class="muted text-13 empty">这个点还没有复核结论</p>
    <div v-if="!auth.isViewer" class="form">
      <el-select v-model="label" size="small" class="label" :teleported="false" aria-label="复核结论">
        <el-option v-for="(text, key) in ANNOTATION_LABELS" :key="key" :value="key" :label="text" />
      </el-select>
      <el-input v-model="annotator" size="small" class="who" placeholder="标注人" maxlength="80" />
      <el-input v-model="note" size="small" class="note" placeholder="备注（可选）" maxlength="500" />
      <el-button size="small" type="primary" :loading="submitting" @click="submit">提交复核</el-button>
    </div>
  </div>
</template>

<style scoped>
.review h5 { margin: 0 0 var(--space-2); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text-primary); }
.review h5 .muted { font-weight: var(--fw-regular); font-size: var(--fs-12); margin-left: var(--space-1); }
.tags { display: flex; flex-wrap: wrap; gap: var(--space-1); margin-bottom: var(--space-2); }
.empty { margin: 0 0 var(--space-2); }
.form { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.form :deep(.el-button) { margin-left: 0; }
.label { width: 124px; }
.who { width: 100px; }
.note { flex: 1; min-width: 120px; }
</style>
