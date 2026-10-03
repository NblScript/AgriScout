/**
 * 页面自报面包屑（计划 0018）：传一个返回各段的函数，数据加载后自动更新；页面卸载时清掉自己设的那份。
 * 不调用时顶栏按导航归属和路由标题显示。
 */
import { onBeforeUnmount, watchEffect } from 'vue'
import { useUiStore, type Crumb } from '../stores/ui'

let owners = 0

export function useBreadcrumb(source: () => Crumb[]) {
  const ui = useUiStore()
  const owner = ++owners
  const stop = watchEffect(() => ui.setTrail(source(), owner))
  onBeforeUnmount(() => {
    stop()
    ui.clearTrail(owner)
  })
}
