import 'vue-router'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题：顶栏面包屑末段与浏览器标签页标题 */
    title?: string
    /** 不套管理台外壳（登录页、展示屏） */
    bare?: boolean
    /** 免登录 */
    public?: boolean
    /** 仅管理员 */
    admin?: boolean
    /** 路由参数 id 是地块 id：顶栏切换地块时留在同一子页 */
    fieldScoped?: boolean
  }
}
