import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: '登录', bare: true, public: true },
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
      meta: { title: '数据总览', bare: true },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { title: '系统状态', icon: 'Odometer' },
    },
 {
      path: '/fields',
      name: 'fields',
      component: () => import('../views/FieldsView.vue'),
      meta: { title: '地块管理', icon: 'MapLocation' },
    },
    {
      path: '/fields/:id/units',
      name: 'field-units',
      component: () => import('../views/UnitsView.vue'),
      meta: { title: '株档案' },
    },
    {
      path: '/fields/:id/plan',
      name: 'field-plan',
      component: () => import('../views/PlanView.vue'),
      meta: { title: '巡检计划' },
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
      meta: { title: '作物管理', icon: 'Cherry' },
    },
    {
      path: '/plantings',
      name: 'plantings',
      component: () => import('../views/PlantingsView.vue'),
      meta: { title: '种植记录', icon: 'Calendar' },
    },
    {
      path: '/devices',
      name: 'devices',
      component: () => import('../views/DevicesView.vue'),
      meta: { title: '设备管理', icon: 'Cpu' },
    },
    {
      path: '/rule-revisions',
      name: 'rule-revisions',
      component: () => import('../views/RuleRevisionsView.vue'),
      meta: { title: '规则修订审批', icon: 'EditPen' },
    },
    {
      path: '/research-loop',
      name: 'research-loop',
      component: () => import('../views/ResearchLoopView.vue'),
      meta: { title: '研究闭环', icon: 'DataAnalysis' },
    },
    {
      path: '/patrols',
      name: 'patrols',
      component: () => import('../views/PatrolsView.vue'),
      meta: { title: '巡检任务', icon: 'VideoCamera' },
    },
    {
      path: '/patrols/:id',
      name: 'patrol-detail',
      component: () => import('../views/PatrolDetailView.vue'),
      meta: { title: '巡检回放' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

/* 登录守卫（决策 D15）：未登录一律去登录页并带回跳地址；管理员页面按角色放行。 */
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    return to.name === 'login' && auth.isAuthenticated ? '/dashboard' : true
  }
  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && !auth.isAdmin) return '/dashboard'
  return true
})

export default router
