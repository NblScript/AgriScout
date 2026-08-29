import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
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

export default router
