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
  /** dark：暗色观感（同源瓦片+CSS 滤镜）+ 发光轨迹；默认 light 保持管理页观感 */
  theme?: 'light' | 'dark'
}>()

const emit = defineEmits<{ (e: 'select', pointId: number): void }>()

const container = ref<HTMLDivElement>()
let map: L.Map | null = null
let boundaryLayer: L.Polygon | null = null
let trackLayer: L.LayerGroup | null = null
let pointsLayer: L.LayerGroup | null = null
let highlight: L.CircleMarker | null = null

const TILES = {
  // 底图唯一源 = 本地高德瓦片 /gdmaptiles/*（tools/download_tiles.py 预缓存 13-18 级）。
  // 高德为 GCJ-02 坐标系：WGS84 轨迹叠加存在固有百米级偏移，演示以相对位置为主可接受。
  // 无在线回退（历史：OSM 封锁/CARTO 要求 key 均不可靠）；视图被 minZoom+maxBounds 钳制。
  url: '/gdmaptiles/{z}/{x}/{y}.png',
  attribution: '&copy; 高德地图',
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
  // 只按地块边界取景：轨迹/点理论上都在边界内；脏测试数据（如经度 10 的
  // 历史点位）会把 fitBounds 拖到半个亚洲导致视图跑出缓存区
  const ring = props.boundary?.coordinates?.[0]
  if (ring?.length) {
    map.fitBounds(L.latLngBounds(ring.map(([lng, lat]) => [lat, lng] as L.LatLngExpression)).pad(0.15))
    return
  }
  const latlngs: L.LatLngExpression[] = []
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

const MAPCODE_VERSION = 'MV8-amap-20260828'

function applyBoundsClamp() {
  // 视图钳制在缓存覆盖范围内：maxBounds=地块边界外扩 0.3（约±0.8km < 缓存半径1.2km），
  // minZoom=13（缓存最低级）。钳制后演示视图内本地瓦片恒命中，物理上不依赖外网。
  if (!map) return
  const ring = props.boundary?.coordinates?.[0]
  if (!ring?.length) return
  const bounds = L.latLngBounds(ring.map(([lng, lat]) => [lat, lng] as L.LatLngExpression))
  map.setMaxBounds(bounds.pad(0.3))
  map.setMinZoom(13)
}

onMounted(() => {
  if (!container.value) return
  // 版本标记：控制台确认实际运行的代码（排查 HMR 僵尸实例/浏览器缓存）
  console.info(`[MapCanvas] ${MAPCODE_VERSION}`)
  map = L.map(container.value, {
    attributionControl: true,
    // 缩放范围与高德瓦片缓存严格对齐（缓存 13-18 级）
    minZoom: 13,
    maxZoom: 18,
  })
  L.tileLayer(TILES.url, { minZoom: 13, maxZoom: 18, attribution: TILES.attribution }).addTo(map)
  renderBoundary()
  renderTrack()
  renderPoints()
  renderHighlight()
  fitAll()
  applyBoundsClamp()
})

// 主题切换：重绘配色相关图层（瓦片同源，暗色靠 CSS 滤镜，无需换底图）
watch(() => props.theme, () => {
  renderBoundary()
  renderTrack()
})

watch(() => props.boundary, () => {
  renderBoundary()
  applyBoundsClamp()
})
watch(() => props.track, renderTrack)
watch(() => props.points, renderPoints)
watch(() => props.selectedIndex, renderHighlight)

// 数据整体替换后重新取景
watch(() => [props.boundary, props.track, props.points], () => {
  // 延迟到下一帧，等图层渲染完成；先钳制再取景，脏数据拖不飞视图
  requestAnimationFrame(() => {
    applyBoundsClamp()
    fitAll()
  })
})

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="container" class="map-canvas" :class="{ 'theme-dark': theme === 'dark' }">
    <span class="mv-badge" :title="MAPCODE_VERSION">{{ MAPCODE_VERSION.split('-')[0] }}</span>
  </div>
</template>

<style scoped>
.map-canvas {
  width: 100%;
  height: 100%;
  min-height: 380px;
}
/* 运行版本徽标：截图可见，用于排查浏览器缓存/僵尸实例 */
.mv-badge {
  position: absolute;
  top: 4px;
  right: 6px;
  z-index: 600;
  font-size: 9px;
  font-family: monospace;
  color: #9aa79a;
  background: rgba(255, 255, 255, 0.7);
  padding: 1px 5px;
  border-radius: 3px;
  pointer-events: none;
}
/* 暗色观感：同源瓦片反相+色相旋转，免第二套瓦片（离线演示同样生效） */
.map-canvas.theme-dark :deep(.leaflet-tile) {
  filter: invert(1) hue-rotate(180deg) brightness(0.92) contrast(0.92);
}
.map-canvas.theme-dark :deep(.leaflet-container) {
  background: #0d1a12;
}
</style>
