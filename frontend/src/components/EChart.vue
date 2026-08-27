<script setup lang="ts">
/** ECharts 薄封装：option 驱动、容器自适应、随组件销毁。
 *  不引 vue-echarts：依赖更少，行为与地图组件同等可控。 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
// 按需注册：全量 echarts 会让 chunk 超过 1.2MB（gzip 400+）
import * as echarts from 'echarts/core'
import { BarChart, GaugeChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
// 类型走完整包定义（type-only，不参与运行时打包）
import type { EChartsOption } from 'echarts'

echarts.use([
  BarChart,
  GaugeChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = defineProps<{
  option: EChartsOption
  /** 大屏内固定尺寸时关闭自动 resize（外层已等比缩放） */
  autoResize?: boolean
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

onMounted(() => {
  if (!container.value) return
  chart = echarts.init(container.value)
  chart.setOption(props.option)
  watch(
    () => props.option,
    (opt) => chart?.setOption(opt, { notMerge: true }),
    { deep: true },
  )
  if (props.autoResize !== false) {
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(container.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="container" class="e-chart" />
</template>

<style scoped>
.e-chart {
  width: 100%;
  height: 100%;
  min-height: 120px;
}
</style>
