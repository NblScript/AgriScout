<script setup lang="ts">
/**
 * 盲评判读（计划 0007 P1-9，D25）：一次一张，只给照片。看不到株号、拍摄时间、模型分数、入选原因和别人的判读；
 * 二次判读时给出前两次的判读（不显示是谁）。判读人取登录账号；数字键 1–4 对应四个选项。手机可用。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Hide } from '@element-plus/icons-vue'
import { blindReviewApi } from '../api'
import { errMsg } from '../api/http'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import SectionCard from '../components/ui/SectionCard.vue'
import { useBreadcrumb } from '../composables/useBreadcrumb'
import { useAuthStore } from '../stores/auth'
import { BLIND_OPTIONS, type BlindLabel, type BlindReviewBatch, type BlindReviewTask } from '../types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const batchId = Number(route.params.id)
const batch = ref<BlindReviewBatch | null>(null)
const task = ref<BlindReviewTask | null>(null)
const loading = ref(true)
const submitting = ref(false)
const done = ref(0)

const LABEL_TEXT: Record<string, string> = Object.fromEntries(BLIND_OPTIONS.map((o) => [o.label, o.text]))
useBreadcrumb(() => [{ label: '盲法复核', to: '/blind-review' }, { label: batch.value?.name ?? '判读' }])

const priorText = computed(() => (task.value?.prior_labels ?? []).map((l) => `「${LABEL_TEXT[l] ?? l}」`).join('，一位判'))

async function loadNext() {
  task.value = await blindReviewApi.next(batchId)
}

async function load() {
  loading.value = true
  try {
    batch.value = await blindReviewApi.get(batchId)
    done.value = batch.value.summary.my_votes ?? 0
    await loadNext()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}

async function vote(label: BlindLabel) {
  const current = task.value
  if (!current || submitting.value || auth.isViewer) return
  submitting.value = true
  try {
    await blindReviewApi.vote(batchId, current.item_id, label)
    done.value += 1
    await loadNext()
  } catch (e) {
    ElMessage.error(errMsg(e))
    await loadNext()
  } finally { submitting.value = false }
}

function onKey(event: KeyboardEvent) {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return
  const option = BLIND_OPTIONS[Number(event.key) - 1]
  if (option) void vote(option.label)
}
onMounted(() => {
  void load()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <PageHeader :title="batch?.name ?? '盲评判读'" :subtitle="`你已判读 ${done} 张；看不到株号、拍摄时间、模型分数和入选原因`">
    <template #actions>
      <el-button :icon="ArrowLeft" @click="router.push('/blind-review')">返回批次</el-button>
    </template>
  </PageHeader>

  <SectionCard v-loading="loading" class="session">
    <template v-if="task">
      <div class="meta text-13">
        <span>第 {{ task.position }} / {{ task.item_count }} 张</span>
        <el-tag v-if="task.round === 2" size="small" type="warning" effect="plain">二次判读</el-tag>
      </div>
      <el-alert v-if="task.round === 2" type="warning" :closable="false" show-icon class="dispute"
                :title="`两位判读人意见不一致：一位判${priorText}。请再看一次并定论。`" />
      <div class="photo">
        <el-image v-if="task.photo_url" :src="task.photo_url" :preview-src-list="[task.photo_url]" fit="contain" preview-teleported />
        <span v-else class="muted">这张没有照片</span>
      </div>
      <div class="choices">
        <el-button v-for="(option, index) in BLIND_OPTIONS" :key="option.label" size="large"
                   :type="option.label === 'other' ? 'default' : 'primary'" :plain="option.label !== 'other'"
                   :disabled="submitting || auth.isViewer" @click="vote(option.label)">
          <span class="key">{{ index + 1 }}</span>{{ option.text }}
        </el-button>
      </div>
      <p v-if="auth.isViewer" class="muted text-12">只读账号只能翻看，不能判读。</p>
    </template>
    <EmptyState v-else-if="!loading" :icon="Hide" title="这一批没有需要你判读的照片了"
                description="两人都判过的照片会自动定论；有分歧的会交给第三人二次判读">
      <el-button @click="router.push('/blind-review')">返回批次</el-button>
    </EmptyState>
  </SectionCard>
</template>

<style scoped>
.session { max-width: 960px; }
.meta { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); }
.dispute { margin-bottom: var(--space-3); }
.photo {
  display: flex; align-items: center; justify-content: center;
  height: min(62vh, 640px); background: var(--bg-subtle); border-radius: var(--radius-md); overflow: hidden;
}
.photo .el-image { width: 100%; height: 100%; }
.choices { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); margin-top: var(--space-4); }
.choices .el-button { margin: 0; }
.key { font-family: var(--font-mono); font-size: 12px; opacity: 0.6; margin-right: var(--space-2); }
@media (max-width: 640px) {
  .photo { height: 50vh; }
  .choices { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
