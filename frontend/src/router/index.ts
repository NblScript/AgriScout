import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

/** 登录后的落脚页：工作台（计划 0018） */
export const HOME_PATH = '/home'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: HOME_PATH },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: '登录', bare: true, public: true },
    },
    {
      path: '/home',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
      meta: { title: '工作台' },
    },
    {
      path: '/confirm',
      name: 'confirm',
      component: () => import('../views/ConfirmQueueView.vue'),
      meta: { title: '待确认' },
    },
    {
      path: '/users',
      name: 'users',
      component: () => import('../views/UsersView.vue'),
      meta: { title: '用户管理', admin: true },
    },
    {
      path: '/screen',
      name: 'screen',
      component: () => import('../views/BigScreenView.vue'),
      meta: { title: '展示屏', bare: true },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { title: '系统状态' },
    },
    {
      path: '/fields',
      name: 'fields',
      component: () => import('../views/FieldsView.vue'),
      meta: { title: '大棚与地块' },
    },
    {
      path: '/fields/:id/units',
      name: 'field-units',
      component: () => import('../views/UnitsView.vue'),
      meta: { title: '株档案', fieldScoped: true },
    },
    {
      path: '/fields/:id/plan',
      name: 'field-plan',
      component: () => import('../views/PlanView.vue'),
      meta: { title: '巡检计划', fieldScoped: true },
    },
    {
      path: '/units/:id',
      name: 'unit-timeline',
      component: () => import('../views/UnitTimelineView.vue'),
      meta: { title: '单株时间线' },
    },
    {
      path: '/crops',
      name: 'crops',
      component: () => import('../views/CropsView.vue'),
      meta: { title: '作物管理' },
    },
    {
      path: '/plantings',
      name: 'plantings',
      component: () => import('../views/PlantingsView.vue'),
      meta: { title: '种植记录' },
    },
    {
      path: '/devices',
      name: 'devices',
      component: () => import('../views/DevicesView.vue'),
      meta: { title: '设备管理' },
    },
    {
      path: '/rule-revisions',
      name: 'rule-revisions',
      component: () => import('../views/RuleRevisionsView.vue'),
      meta: { title: '规则修订审批' },
    },
    {
      path: '/research-loop',
      name: 'research-loop',
      component: () => import('../views/ResearchLoopView.vue'),
      meta: { title: '研究闭环' },
    },
    {
      path: '/patrols',
      name: 'patrols',
      component: () => import('../views/PatrolsView.vue'),
      meta: { title: '巡检记录' },
    },
    {
      path: '/patrols/:id',
      name: 'patrol-detail',
      component: () => import('../views/PatrolDetailView.vue'),
      meta: { title: '巡检回放' },
    },
    { path: '/:pathMatch(.*)*', redirect: HOME_PATH },
  ],
})

/* 登录守卫（决策 D15）：未登录一律去登录页并带回跳地址；管理员页面按角色放行。 */
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    return to.name === 'login' && auth.isAuthenticated ? HOME_PATH : true
  }
  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && !auth.isAdmin) return HOME_PATH
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 巡知` : '巡知 · 设施大棚病害主动巡检平台'
})

export default router
