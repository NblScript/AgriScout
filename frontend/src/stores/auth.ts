/** 登录态（决策 D15）：令牌与当前用户存 localStorage，刷新页面不掉线；过期即视为未登录。 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '../api'
import { setAuthToken } from '../api/http'
import type { User } from '../types'

const STORAGE_KEY = 'agriscout_auth'

interface Persisted {
  token: string
  expiresAt: string
  user: User
}

function readPersisted(): Persisted | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as Persisted
    return new Date(data.expiresAt).getTime() > Date.now() ? data : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const saved = readPersisted()
  const token = ref<string | null>(saved?.token ?? null)
  const expiresAt = ref<string | null>(saved?.expiresAt ?? null)
  const user = ref<User | null>(saved?.user ?? null)
  setAuthToken(token.value)

  const isAuthenticated = computed(() =>
    !!token.value && !!expiresAt.value && new Date(expiresAt.value).getTime() > Date.now())
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isViewer = computed(() => user.value?.role === 'viewer')

  function persist() {
    try {
      if (token.value && expiresAt.value && user.value) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: token.value, expiresAt: expiresAt.value, user: user.value }))
      } else {
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch { /* 隐私模式等存储不可用：仅本页会话有效 */ }
  }

  async function login(username: string, password: string) {
    const result = await authApi.login(username, password)
    token.value = result.access_token
    expiresAt.value = result.expires_at
    user.value = result.user
    setAuthToken(token.value)
    persist()
  }

  /** 以服务端为准刷新用户信息（角色可能已被管理员修改）。 */
  async function refreshMe() {
    if (!token.value) return
    user.value = await authApi.me()
    persist()
  }

  function logout() {
    token.value = null
    expiresAt.value = null
    user.value = null
    setAuthToken(null)
    persist()
  }

  return { token, expiresAt, user, isAuthenticated, isAdmin, isViewer, login, refreshMe, logout }
})
