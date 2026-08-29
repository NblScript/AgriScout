/** CRUD 表单弹窗通用逻辑：四管理页（地块/作物/设备/种植）的同步抽提。
 *
 * submit 需调用方传 payload 构造器（各实体字段裁剪/trim/null 转换不同），
 * 其余生命周期（开弹窗/回填/校验/提交/删除确认）全部收口于此。
 */
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { errMsg } from '../api/http'

export interface CrudDialogOptions<T extends { id: number }, F extends object> {
  /** 弹窗关闭后刷新列表 */
  reload: () => Promise<void>
  create: (payload: Record<string, unknown>) => Promise<unknown>
  update: (id: number, payload: Record<string, unknown>) => Promise<unknown>
  remove: (id: number) => Promise<unknown>
  /** 新增时的空表单 */
  emptyForm: () => F
  /** 编辑时行数据 → 表单回填 */
  toForm: (row: T) => F
  /** 实体中文名（提示文案用），如 "设备" */
  entityName: string
}

export function useCrudDialog<T extends { id: number }, F extends object>(
  opts: CrudDialogOptions<T, F>,
) {
  const dialogVisible = ref(false)
  const editingId = ref<number | null>(null)
  const submitting = ref(false)
  const formRef = ref<FormInstance>()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- reactive() 与泛型 F 的协变限制，调用方 form 类型仍为 F
  const form: F = reactive(opts.emptyForm()) as any

  function openCreate() {
    editingId.value = null
    Object.assign(form, opts.emptyForm())
    dialogVisible.value = true
  }

  function openEdit(row: T) {
    editingId.value = row.id
    Object.assign(form, opts.toForm(row))
    dialogVisible.value = true
  }

  /** payload 构造器：由调用方把 form 裁剪成 API 载荷（trim/null 转换等） */
  async function submit(buildPayload: (form: F, editing: boolean) => Record<string, unknown>) {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    submitting.value = true
    try {
      if (editingId.value == null) {
        await opts.create(buildPayload(form, false))
        ElMessage.success(`${opts.entityName}已创建`)
      } else {
        await opts.update(editingId.value, buildPayload(form, true))
        ElMessage.success(`${opts.entityName}已更新`)
      }
      dialogVisible.value = false
      await opts.reload()
    } catch (e) {
      ElMessage.error(errMsg(e))
    } finally {
      submitting.value = false
    }
  }

  async function removeRow(row: T, displayName: string) {
    try {
      await ElMessageBox.confirm(`确认删除${opts.entityName}「${displayName}」？`, '删除确认', {
        type: 'warning',
      })
    } catch {
      return
    }
    try {
      await opts.remove(row.id)
      ElMessage.success('已删除')
      await opts.reload()
    } catch (e) {
      ElMessage.error(errMsg(e))
    }
  }

  return { dialogVisible, editingId, submitting, formRef, form, openCreate, openEdit, submit, removeRow }
}
