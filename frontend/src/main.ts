import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './styles/theme.css'
import './style.css'
import App from './App.vue'
import router from './router'
import { setUnauthorizedHandler } from './api/http'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
app.use(createPinia())
app.use(router)

// 任何接口返回 401（令牌过期/账号被停用）：清登录态，回登录页并带回跳地址
setUnauthorizedHandler(() => {
  const auth = useAuthStore()
  if (!auth.token) return
  auth.logout()
  const current = router.currentRoute.value
  if (current.name !== 'login') {
    router.replace({ name: 'login', query: { redirect: current.fullPath, reason: 'expired' } })
  }
})
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
