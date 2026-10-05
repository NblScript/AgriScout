/** 跟着媒体查询变的布尔值（手机宽度下抽屉占满屏、表单换行等用）；组件卸载时自动解绑。 */
import { onBeforeUnmount, ref, type Ref } from 'vue'

export const PHONE_QUERY = '(max-width: 767px)'

export function useMediaQuery(query: string): Ref<boolean> {
  const list = window.matchMedia(query)
  const matches = ref(list.matches)
  const onChange = (event: MediaQueryListEvent) => { matches.value = event.matches }
  list.addEventListener('change', onChange)
  onBeforeUnmount(() => list.removeEventListener('change', onChange))
  return matches
}
