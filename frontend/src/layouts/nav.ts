/** 侧栏导航（计划 0018 设计 3）：按「工作 / 研究 / 管理」分组；展示屏在侧栏和顶栏各有一个入口。 */
import type { Component } from 'vue'
import {
  Calendar, Camera, Cherry, Cpu, DataAnalysis, EditPen, Hide, House, MapLocation, Monitor, Odometer, Stamp, User,
} from '@element-plus/icons-vue'
import type { Field } from '../types'

export interface NavItem {
  label: string
  path: string
  icon: Component
  /** 这些路径前缀也算本项（大棚下的计划、株档案、单株时间线都归「大棚与地块」） */
  match?: string[]
  adminOnly?: boolean
  /** 角标：confirm = 未完成的确认任务数 */
  badge?: 'confirm'
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: '工作',
    items: [
      { label: '工作台', path: '/home', icon: House },
      { label: '待确认', path: '/confirm', icon: Stamp, badge: 'confirm' },
      { label: '大棚与地块', path: '/fields', icon: MapLocation, match: ['/fields', '/units'] },
      { label: '巡检记录', path: '/patrols', icon: Camera },
      { label: '展示屏', path: '/screen', icon: Monitor },
    ],
  },
  {
    label: '研究',
    items: [
      { label: '研究闭环', path: '/research-loop', icon: DataAnalysis },
      { label: '盲法复核', path: '/blind-review', icon: Hide },
      { label: '规则修订审批', path: '/rule-revisions', icon: EditPen },
    ],
  },
  {
    label: '管理',
    items: [
      { label: '作物', path: '/crops', icon: Cherry },
      { label: '种植记录', path: '/plantings', icon: Calendar },
      { label: '设备', path: '/devices', icon: Cpu },
      { label: '用户', path: '/users', icon: User, adminOnly: true },
      { label: '系统状态', path: '/dashboard', icon: Odometer },
    ],
  },
]

function covers(prefix: string, path: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`)
}

/** 当前路径归属的导航项（取最长前缀）。 */
export function matchNav(path: string): NavItem | undefined {
  let best: NavItem | undefined
  let bestLength = 0
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      for (const prefix of item.match ?? [item.path]) {
        if (covers(prefix, path) && prefix.length > bestLength) {
          best = item
          bestLength = prefix.length
        }
      }
    }
  }
  return best
}

/** 导航项所在的分组 */
export function navGroupOf(item: NavItem): NavGroup | undefined {
  return NAV_GROUPS.find((group) => group.items.includes(item))
}

/** 地块的落脚页：大棚和大田都进详情页 `/fields/:id`（大田只有概览和巡检记录两个标签）。 */
export function fieldHomePath(field: Pick<Field, 'id'>): string {
  return `/fields/${field.id}`
}
