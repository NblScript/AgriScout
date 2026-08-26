import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 界面全局状态。登录态已砍除（基线 B4）；当前地块选择等留待 M6 地图使用。 */
export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  return { sidebarCollapsed, toggleSidebar }
})
