/** 棚内环境图表的公共配置（巡检计划页与展示屏共用）：颜色取设计令牌，时间按田间时区。 */
import type { EChartsOption } from 'echarts'
import { cssVar } from '../styles/tokens'
import type { EnvHour } from '../types'
import { fieldParts } from './fieldTime'

/** 坐标轴、网格、提示框的公共样式 */
export function chartBase(fontSize = 12) {
  const axis = cssVar('--chart-axis', '#66726b')
  const grid = cssVar('--chart-grid', '#e3e8e5')
  return {
    textStyle: { fontFamily: cssVar('--font-sans', 'sans-serif'), fontSize },
    axisLine: { lineStyle: { color: grid } },
    axisLabel: { color: axis, fontSize },
    splitLine: { lineStyle: { color: grid } },
    legend: { top: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 8, textStyle: { color: axis, fontSize } },
  }
}

/** 「10/03 06时」 */
export function hourLabel(iso: string): string {
  const { day, hour } = fieldParts(iso)
  return `${day} ${String(hour).padStart(2, '0')}时`
}

/** 逐小时温度、相对湿度（可选露点差）曲线；缺测小时为 null，曲线断开而不是插值 */
export function hourlyEnvOption(
  hours: EnvHour[],
  opts: { dewpoint?: boolean; fontSize?: number; splitNumber?: number } = {},
): EChartsOption {
  const base = chartBase(opts.fontSize)
  const dewpoint = opts.dewpoint ?? true
  const names = ['温度 ℃', '相对湿度 %', ...(dewpoint ? ['露点差 ℃'] : [])]
  return {
    textStyle: base.textStyle,
    tooltip: { trigger: 'axis' },
    legend: { ...base.legend, data: names },
    grid: { left: 44, right: 44, top: 36, bottom: 28 },
    xAxis: {
      type: 'category',
      data: hours.map((h) => hourLabel(h.hour)),
      axisLine: base.axisLine,
      axisTick: { show: false },
      // 只在田间日期的零点标刻度
      axisLabel: { ...base.axisLabel, interval: (index: number) => fieldParts(hours[index].hour).hour === 0, formatter: (v: string) => v.slice(0, 5) },
    },
    yAxis: [
      { type: 'value', name: '℃', splitNumber: opts.splitNumber, nameTextStyle: base.axisLabel, axisLabel: base.axisLabel, splitLine: base.splitLine },
      // 刻度少时湿度轴按 25% 一格，免得出现 0/30/60/90/100 这样的不等距刻度
      { type: 'value', name: '%', min: 0, max: 100, ...(opts.splitNumber ? { interval: 25 } : {}), nameTextStyle: base.axisLabel, axisLabel: base.axisLabel, splitLine: { show: false } },
    ],
    series: [
      { name: '温度 ℃', type: 'line', showSymbol: false, data: hours.map((h) => h.temp_c), color: cssVar('--chart-warm', '#c8691f') },
      { name: '相对湿度 %', type: 'line', showSymbol: false, yAxisIndex: 1, data: hours.map((h) => h.humidity_pct), color: cssVar('--chart-wet', '#2f6fb0') },
      ...(dewpoint
        ? [{ name: '露点差 ℃', type: 'line' as const, showSymbol: false, data: hours.map((h) => h.dewpoint_depression_min), color: cssVar('--chart-neutral', '#7a857f'), lineStyle: { type: 'dashed' as const } }]
        : []),
    ],
  }
}
