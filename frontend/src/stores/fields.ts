/** 地块列表缓存（计划 0018）：顶栏地块切换器、工作台、面包屑共用，增删改地块后调用 load(true) 刷新。 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fieldsApi } from '../api'
import type { Field } from '../types'

export const useFieldsStore = defineStore('fields', () => {
  const list = ref<Field[]>([])
  const loaded = ref(false)
  let pending: Promise<Field[]> | null = null

  function load(force = false): Promise<Field[]> {
    if (pending) return pending
    if (loaded.value && !force) return Promise.resolve(list.value)
    pending = fieldsApi.list()
      .then((fields) => {
        list.value = fields
        loaded.value = true
        return fields
      })
      .finally(() => { pending = null })
    return pending
  }

  const byId = computed(() => new Map(list.value.map((field) => [field.id, field])))

  return { list, loaded, load, byId }
})
