<script setup lang="ts">
/** Leaflet 薄封装：地块边界 + 巡检轨迹 + 采样点着色散点 + 选中高亮。
 *  用原生 Leaflet 而非包装库：依赖少、行为可控（M6 方案决定①）。 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { NO_ANALYSIS_COLOR, VIGOR_COLORS, type CapturePointFull } from '../types'

const props = defineProps<{
  boundary: { type: string; coordinates: number[][][] } | null
  track: { type: string; coordinates: number[][] } | null
  points: CapturePointFull[]
  selectedIndex: number | null
  /** dark：暗色底图 + 发光轨迹（大屏/回放大屏化用）；默认 light 保持管理页观感 */
  theme?: 'light' | 'dark'
}>()

const emit = defineEmits<{ (e: 'select', pointId: number): void }>()

const container = ref<HTMLDivElement>()
let map: L.Map | null = null
let tileLayer: L.TileLayer | null = null
let boundaryLayer: L.Polygon | null = null
let trackLayer: L.LayerGroup | null = null
let pointsLayer: L.LayerGroup | null = null
let highlight: L.CircleMarker | null = null

const TILES = {
  light: {
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap',
  },
  dark: {
    // 暗色底图（CARTO），离线化见独立任务
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution: '&copy; OpenStreetMap &copy; CARTO',
  },
}

function themeColors() {
  const dark = props.theme === 'dark'
  return {
    boundary: dark ? '#4ade80' : '#2e5d34',
    boundaryFill: dark ? 0.08 : 0.06,
    track: dark ? '#38bdf8' : '#1565c0',
  }
}

function pointColor(p: CapturePointFull): string {
  const v = p.analysis?.vigor_level
  return v ? VIGOR_COLORS[v] ?? NO_ANALYSIS_COLOR : NO_ANALYSIS_COLOR
}

function fitAll() {
  if (!map) return
  const latlngs: L.LatLngExpression[] = []
  const ring = props.boundary?.coordinates?.[0]
  if (ring?.length) latlngs.push(...ring.map(([lng, lat]) => [lat, lng] as L.LatLngExpression))
  const coords = props.track?.coordinates
  if (coords?.length) latlngs.push(...coords.map(([lng, lat]) => [lat, lng] as L.LatLngExpression))
  props.points.forEach((p) => latlngs.push([p.lat, p.lng]))
  if (latlngs.length) map.fitBounds(L.latLngBounds(latlngs).pad(0.15))
}

function renderBoundary() {
  if (!map) return
  boundaryLayer?.remove()
  boundaryLayer = null
  const ring = props.boundary?.coordinates?.[0]
  if (ring?.length) {
    const c = themeColors()
    boundaryLayer = L.polygon(
      ring.map(([lng, lat]) => [lat, lng]),
      { color: c.boundary, weight: 2, fillOpacity: c.boundaryFill },
    ).addTo(map)
  }
}

function renderTrack() {
  if (!map) return
  trackLayer?.remove()
  trackLayer = null
  const coords = props.track?.coordinates
  if (coords?.length) {
    const latlngs = coords.map(([lng, lat]) => [lat, lng] as L.LatLngExpression)
    trackLayer = L.layerGroup().addTo(map)
    if (props.theme === 'dark') {
      // 双层发光轨迹：底层宽半透明 + 上层亮线
      L.polyline(latlngs, { color: '#38bdf8', weight: 7, opacity: 0.18 }).addTo(trackLayer)
      L.polyline(latlngs, {
        color: themeColors().track, weight: 2, opacity: 0.9, dashArray: '6 4',
      }).addTo(trackLayer)
    } else {
      L.polyline(latlngs, {
        color: themeColors().track, weight: 2.5, opacity: 0.75, dashArray: '6 4',
      }).addTo(trackLayer)
    }
  }
}

function renderPoints() {
  if (!map) return
  pointsLayer?.remove()
  pointsLayer = L.layerGroup().addTo(map)
  for (const p of props.points) {
    const stressed = !!p.analysis?.disease_detections?.length
    L.circleMarker([p.lat, p.lng], {
      radius: 4.5,
      color: stressed ? '#ffd54f' : '#ffffff',
      weight: stressed ? 2 : 1,
      fillColor: pointColor(p),
      fillOpacity: 0.9,
    })
      .bindTooltip(`#${p.seq} · ${pointColor(p) === NO_ANALYSIS_COLOR ? '未分析' : `长势${p.analysis?.vigor_level}`}`)
      .on('click', () => emit('select', p.id))
      .addTo(pointsLayer)
  }
}

function renderHighlight() {
  if (!map) return
  highlight?.remove()
  highlight = null
  if (props.selectedIndex != null && props.points[props.selectedIndex]) {
    const p = props.points[props.selectedIndex]
    highlight = L.circleMarker([p.lat, p.lng], {
      radius: 9, color: '#1e88e5', weight: 3, fill: false,
    }).addTo(map)
  }
}

onMounted(() => {
  if (!container.value) return
  map = L.map(container.value, { attributionControl: true })
  const t = TILES[props.theme === 'dark' ? 'dark' : 'light']
  tileLayer = L.tileLayer(t.url, { maxZoom: 19, attribution: t.attribution }).addTo(map)
  renderBoundary()
  renderTrack()
  renderPoints()
  renderHighlight()
  fitAll()
})

// 主题切换：换底图并重绘配色相关图层
watch(() => props.theme, () => {
  if (!map) return
  tileLayer?.remove()
  const t = TILES[props.theme === 'dark' ? 'dark' : 'light']
  tileLayer = L.tileLayer(t.url, { maxZoom: 19, attribution: t.attribution }).addTo(map)
  renderBoundary()
  renderTrack()
})

watch(() => props.boundary, renderBoundary)
watch(() => props.track, renderTrack)
watch(() => props.points, renderPoints)
watch(() => props.selectedIndex, renderHighlight)

// 数据整体替换后重新取景
watch(() => [props.boundary, props.track, props.points], () => {
  // 延迟到下一帧，等图层渲染完成
  requestAnimationFrame(fitAll)
})

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="container" class="map-canvas" />
</template>

<style scoped>
.map-canvas {
  width: 100%;
  height: 100%;
  min-height: 380px;
}
</style>
