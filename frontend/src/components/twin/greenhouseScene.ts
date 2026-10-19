/**
 * 数字孪生大棚的 Three.js 场景（数媒大赛）：棚体、垄、植株按「垄 × 株」摆放并按当前状态着色，
 * 今日计划的株脚下画名单色圈，「推给人确认」的株立光柱；巡检车按计划里要拍的株沿过道行驶、停车、两次闪光（正面、叶背）。
 * 只管画面和交互，不取数：数据由 TwinView 传入，点株、悬停、巡检车进度通过回调交回页面。
 * 视觉走「数字孪生」科技风：深色底、发光网格与扫描环、棚架发光轮廓、辉光后处理；异常株自发光（早期弱、明显强），
 * 健康株压暗，一眼看出哪里有问题；巡检车的计划路线画成光带，光点沿路线流动。
 * 棚体尺寸是示意（行距 1.5 m、株距 0.45 m），不是实测。
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import type { PlanListName, PlantStateValue } from '../../types'

export interface TwinPlant {
  unitId: number
  key: string
  row: number | null
  pos: number | null
  state: PlantStateValue
  /** 0–1 的风险分（模型分或计划分），没有为空，热力层不画 */
  risk: number | null
  /** 今日计划里所在名单；不在计划里为空 */
  list: PlanListName | null
}

export interface TwinPalette {
  state: Record<PlantStateValue, string>
  task: Record<PlanListName, string>
  bgTop: string
  bgBottom: string
  ground: string
  floor: string
  soil: string
  wall: string
  frame: string
  film: string
  accent: string
  rover: string
  heatLow: string
  heatMid: string
  heatHigh: string
}

export type Facility = 'solar_greenhouse' | 'plastic_tunnel'
export type LightMode = 'dawn' | 'day'

export interface RoverStatus {
  phase: 'idle' | 'moving' | 'shooting' | 'docking'
  unitId: number | null
  /** 第几个拍照点（从 1 起），总数 */
  index: number
  total: number
}

export interface SceneCallbacks {
  onPick?: (unitId: number | null) => void
  onHover?: (unitId: number | null, clientX: number, clientY: number) => void
  onRover?: (status: RoverStatus) => void
}

const ROW_GAP = 1.5
const PLANT_GAP = 0.45
const AISLE_MARGIN = 2.0 // 株列两端到后墙/前沿的过道（前沿棚低，巡检车走的前过道要往里收）
const ROVER_SPEED = 1.8 // 演示加速，米/秒
const SHOOT_SECONDS = 1.5
const LEAVES = 12 // 每株叶片数
const LEAF_SCALE = 1.7 // 叶比实物放大，远景里看得出株状态色
const DOCK_SECONDS = 2.5
const SCAN_SECONDS = 5 // 地面扫描环一圈的时长
const FLOW_DOTS = 36 // 路线上流动的光点数
/** 株状态 → 叶片自发光强度：异常株「亮起来」，健康与不明不发光 */
const STATE_GLOW: Record<PlantStateValue, number> = { healthy: 0.05, early: 0.2, symptomatic: 0.45, unknown: 0 }

type Segment =
  | { kind: 'move'; from: THREE.Vector3; to: THREE.Vector3; dur: number }
  | { kind: 'shoot'; plant: number; at: THREE.Vector3; dur: number; index: number }
  | { kind: 'dock'; at: THREE.Vector3; dur: number }

/** 黄瓜叶五个裂片：中裂片、两侧裂片、两基裂片（角度从叶尖方向起算，弧度）与相对长度 */
const LOBES: [number, number][] = [[0, 1], [1.0, 0.86], [-1.0, 0.86], [1.95, 0.6], [-1.95, 0.6]]
const LEAF_SIZE = 0.24 // 叶柄端到中裂片尖的长度（米，演示前放大）

/** 叶缘半径：裂片尖成锐角、裂片之间是浅缺刻、基部心形凹入，再叠一层细锯齿 */
function leafRadius(theta: number): number {
  let r = 0.5 * (1 - (Math.abs(theta) / Math.PI) ** 3) // 打底：越靠基部越短，到正后方收成心形凹口
  for (const [at, len] of LOBES) {
    const d = Math.abs(theta - at)
    if (d < 0.62) r = Math.max(r, len * (1 - d / 0.62) ** 0.55)
  }
  return r * (1 + 0.03 * Math.sin(theta * 38) * Math.min(1, r * 2))
}

/**
 * 一片黄瓜叶：以叶柄端为圆心按叶缘半径铺放射网格（48 × 4），叶面横向微凹、叶尖下垂、叶缘起伏，
 * 法线重算后受光有明暗；UV 以叶柄端为中心，配叶脉贴图。叶在 XY 平面、沿 +y 伸出，+z 为叶面朝上。
 */
function leafGeometry(): THREE.BufferGeometry {
  const N = 48
  const R = 4
  const pos: number[] = [0, 0, 0]
  const uv: number[] = [0.5, 0.5]
  const span = LEAF_SIZE * 1.1
  for (let j = 1; j <= R; j++) {
    const f = j / R
    for (let i = 0; i < N; i++) {
      const theta = -Math.PI + (i / N) * Math.PI * 2
      const r = leafRadius(theta) * LEAF_SIZE * f
      const x = Math.sin(theta) * r
      const y = Math.cos(theta) * r
      const z = -2.2 * x * x - 1.6 * Math.max(0, y) ** 2 + 0.012 * Math.sin(theta * 5) * f * f
      pos.push(x, y, z)
      uv.push(0.5 + x / (2 * span), 0.5 + y / (2 * span))
    }
  }
  const idx: number[] = []
  for (let i = 0; i < N; i++) idx.push(0, 1 + i, 1 + ((i + 1) % N))
  for (let j = 1; j < R; j++) {
    const a0 = 1 + (j - 1) * N
    const b0 = 1 + j * N
    for (let i = 0; i < N; i++) {
      const i1 = (i + 1) % N
      idx.push(a0 + i, b0 + i, b0 + i1, a0 + i, b0 + i1, a0 + i1)
    }
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  geo.setIndex(idx)
  geo.computeVertexNormals()
  return geo
}

/** 叶脉贴图（灰度，与株状态色相乘）：五条主脉从叶柄端放射到裂片尖，每条再分出侧脉；叶缘略暗 */
function leafTexture(): THREE.Texture {
  const S = 256
  const c = S / 2
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = S
  const ctx = canvas.getContext('2d')!
  const base = ctx.createRadialGradient(c, c, 0, c, c, c)
  base.addColorStop(0, 'rgb(225,225,225)')
  base.addColorStop(0.7, 'rgb(200,200,200)')
  base.addColorStop(1, 'rgb(165,165,165)')
  ctx.fillStyle = base
  ctx.fillRect(0, 0, S, S)
  // 细小斑驳，避免大片纯色
  for (let i = 0; i < 1400; i++) {
    const v = 185 + Math.floor(hash01(i * 3.7) * 40)
    ctx.fillStyle = `rgba(${v},${v},${v},0.35)`
    ctx.fillRect(hash01(i * 1.3) * S, hash01(i * 2.9) * S, 2, 2)
  }
  const toPx = (theta: number, r: number) => [c + Math.sin(theta) * r * (c / 1.1), c - Math.cos(theta) * r * (c / 1.1)]
  ctx.lineCap = 'round'
  for (const [at, len] of LOBES) {
    const [tx, ty] = toPx(at, len * 0.95)
    ctx.strokeStyle = 'rgb(250,250,245)'
    ctx.lineWidth = 3.2
    ctx.beginPath(); ctx.moveTo(c, c); ctx.lineTo(tx, ty); ctx.stroke()
    ctx.lineWidth = 1.4
    for (const k of [0.3, 0.52, 0.72]) {
      for (const side of [-1, 1]) {
        const [sx, sy] = toPx(at, len * k)
        const [ex, ey] = toPx(at + side * 0.42, len * (k + 0.24))
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke()
      }
    }
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

/** 一圈卷须：细螺旋管，长约 0.12 m */
function tendrilGeometry(): THREE.BufferGeometry {
  const pts: THREE.Vector3[] = []
  for (let i = 0; i <= 40; i++) {
    const t = i / 40
    const a = t * Math.PI * 6
    const rad = 0.012 + 0.018 * t
    pts.push(new THREE.Vector3(Math.cos(a) * rad * t, -t * 0.03 + t * t * 0.12, Math.sin(a) * rad * t))
  }
  return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 40, 0.0025, 4)
}

/** 黄瓜花：五片圆瓣，直径约 5 cm，在 XY 平面朝 +z */
function flowerGeometry(): THREE.BufferGeometry {
  const shape = new THREE.Shape()
  for (let i = 0; i <= 60; i++) {
    const a = (i / 60) * Math.PI * 2
    const r = 0.025 * (0.55 + 0.45 * Math.abs(Math.cos(a * 2.5)))
    if (i === 0) shape.moveTo(Math.cos(a) * r, Math.sin(a) * r)
    else shape.lineTo(Math.cos(a) * r, Math.sin(a) * r)
  }
  return new THREE.ShapeGeometry(shape)
}

/** 可复现的伪随机（同一株每次刷新长得一样） */
function hash01(n: number): number {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453
  return x - Math.floor(x)
}

export class GreenhouseScene {
  private renderer: THREE.WebGLRenderer
  private composer: EffectComposer
  private bloom: UnrealBloomPass
  private labelRenderer: CSS2DRenderer
  private scene = new THREE.Scene()
  private camera: THREE.PerspectiveCamera
  private controls: OrbitControls
  private timer = new THREE.Timer()
  private raycaster = new THREE.Raycaster()
  private pointer = new THREE.Vector2()
  private resizeObserver: ResizeObserver
  private frame = 0
  private disposed = false

  private hemi = new THREE.HemisphereLight(0xffffff, 0x223322, 1)
  private sun = new THREE.DirectionalLight(0xffffff, 1.6)
  /** 背后的青色轮廓光，勾出叶缘和棚架 */
  private rim = new THREE.DirectionalLight(0x5fe8d6, 0.6)
  private flash = new THREE.PointLight(0xffffff, 0, 4, 2)

  /** 每次 setData 重建的内容都挂在这里，换棚时整组丢弃 */
  private world = new THREE.Group()
  private plants: TwinPlant[] = []
  private positions: THREE.Vector3[] = []
  private canopy: THREE.InstancedMesh | null = null
  private beams: THREE.InstancedMesh | null = null
  private heat: THREE.Mesh | null = null
  private dew: THREE.Points | null = null
  private glowAttr: THREE.InstancedBufferAttribute | null = null
  private scan: THREE.Mesh | null = null
  private markers: THREE.InstancedMesh | null = null
  private markerBase: THREE.Matrix4[] = []
  private flowDots: THREE.Points | null = null
  private routePts: THREE.Vector3[] = []
  private routeLen: number[] = []
  private hoverMark: THREE.Mesh
  private selectMark: THREE.Group
  private shotRing: THREE.Mesh
  private rover: THREE.Group
  private roverHead: THREE.Object3D
  private flashBulb: THREE.Mesh
  private segments: Segment[] = []
  private roverTime = 0
  private roverTotal = 0
  private lastSegment = -1
  private roverStops = 0

  private hovered: number | null = null
  private selected: number | null = null
  private downAt: { x: number; y: number } | null = null
  private bounds = { xHalf: 5, zHalf: 5, roofH: 4 }

  playing = true

  constructor(private container: HTMLElement, private palette: TwinPalette, private callbacks: SceneCallbacks = {}) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFShadowMap
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    container.appendChild(this.renderer.domElement)

    this.labelRenderer = new CSS2DRenderer()
    this.labelRenderer.domElement.className = 'twin-labels'
    container.appendChild(this.labelRenderer.domElement)

    this.camera = new THREE.PerspectiveCamera(36, 1, 0.1, 400)
    // 辉光后处理：只有亮于阈值的部分（发光轮廓、异常株、光柱、闪光）泛光
    this.composer = new EffectComposer(this.renderer)
    this.composer.addPass(new RenderPass(this.scene, this.camera))
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.85, 0.55, 0.8)
    this.composer.addPass(this.bloom)
    this.composer.addPass(new OutputPass())
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.maxPolarAngle = Math.PI * 0.47
    this.controls.minDistance = 4
    this.controls.maxDistance = 90
    this.controls.autoRotateSpeed = 0.5

    this.sun.castShadow = true
    this.sun.shadow.mapSize.set(2048, 2048)
    this.sun.shadow.bias = -0.0004
    this.rim.position.set(-20, 12, -30)
    this.scene.add(this.hemi, this.sun, this.sun.target, this.rim, this.flash, this.world)

    const accent = new THREE.Color(palette.accent)
    this.hoverMark = new THREE.Mesh(
      new THREE.CylinderGeometry(0.34, 0.34, 2.2, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false }),
    )
    this.hoverMark.visible = false
    this.selectMark = this.makeSelectMark(accent)
    this.shotRing = new THREE.Mesh(
      new THREE.RingGeometry(0.2, 0.26, 40),
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }),
    )
    this.shotRing.rotation.x = -Math.PI / 2
    const { group, head, bulb } = this.makeRover()
    this.rover = group
    this.roverHead = head
    this.flashBulb = bulb
    this.scene.add(this.hoverMark, this.selectMark, this.shotRing, this.rover)

    const el = this.renderer.domElement
    el.addEventListener('pointermove', this.onPointerMove)
    el.addEventListener('pointerdown', this.onPointerDown)
    el.addEventListener('pointerup', this.onPointerUp)
    el.addEventListener('pointerleave', this.onPointerLeave)
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(container)
    this.resize()
    this.setLightMode('dawn')
    this.timer.connect(document)
    this.loop()
  }

  /* ------------------------------------------------------------------ 数据 */

  /** 换棚或首次加载：重建棚体、植株、计划标记和巡检车路线 */
  setData(plants: TwinPlant[], facility: Facility, roverOrder: number[]) {
    this.clearWorld()
    this.plants = plants
    this.layout(plants)
    this.buildShell(facility)
    this.buildRows()
    this.buildPlants()
    this.buildPlanMarks()
    this.buildHeat()
    this.buildDew()
    this.buildRoute(roverOrder)
    this.fitCamera()
    this.select(null)
  }

  /** 刷新：株集合不变时只改颜色和标记，不动镜头和巡检车 */
  updateStates(plants: TwinPlant[]): boolean {
    if (plants.length !== this.plants.length || plants.some((p, i) => p.unitId !== this.plants[i].unitId)) return false
    this.plants = plants
    this.paintCanopy()
    this.world.remove(...this.world.children.filter((c) => c.userData.planMark || c.userData.heat))
    this.buildPlanMarks()
    this.buildHeat()
    return true
  }

  select(unitId: number | null) {
    this.selected = unitId
    const i = unitId == null ? -1 : this.plants.findIndex((p) => p.unitId === unitId)
    this.selectMark.visible = i >= 0
    if (i >= 0) this.selectMark.position.copy(this.positions[i])
  }

  /** 镜头飞到某株附近 */
  focus(unitId: number) {
    const i = this.plants.findIndex((p) => p.unitId === unitId)
    if (i < 0) return
    const p = this.positions[i]
    const target = new THREE.Vector3(p.x, 1, p.z)
    const offset = new THREE.Vector3(3.2, 2.6, 3.6)
    this.tween(target, target.clone().add(offset))
  }

  resetView() {
    this.fitCamera(true)
  }

  setAutoRotate(on: boolean) {
    this.controls.autoRotate = on
  }

  setHeatVisible(on: boolean) {
    if (this.heat) this.heat.visible = on
    this.heatVisible = on
  }
  private heatVisible = false

  private lightMode: LightMode = 'dawn'
  setLightMode(mode: LightMode) {
    this.lightMode = mode
    const dawn = mode === 'dawn'
    const top = new THREE.Color(this.palette.bgTop)
    const bottom = new THREE.Color(this.palette.bgBottom)
    // 清晨：深青夜色 + 暖色低角度晨光；白天：青灰天光，辉光收弱
    const skyTop = dawn ? top.clone().multiplyScalar(0.55) : top.clone().lerp(new THREE.Color(0x3f6f80), 0.6)
    const skyBottom = dawn ? bottom : bottom.clone().lerp(new THREE.Color(0x8fb8b0), 0.55)
    this.scene.background = this.gradientTexture(skyTop, skyBottom)
    this.scene.fog = new THREE.FogExp2(dawn ? bottom.clone().multiplyScalar(0.8) : skyBottom, dawn ? 0.014 : 0.009)
    this.hemi.color.set(dawn ? 0x8fb6d9 : 0xffffff)
    this.hemi.groundColor.set(dawn ? 0x0e1a18 : 0x3a4a44)
    this.hemi.intensity = dawn ? 0.75 : 1.4
    this.sun.color.set(dawn ? 0xffbf8a : 0xffffff)
    this.sun.intensity = dawn ? 1.2 : 2.3
    this.sun.position.set(dawn ? 30 : 12, dawn ? 9 : 30, dawn ? 18 : 22)
    this.rim.intensity = dawn ? 0.9 : 0.35
    this.bloom.strength = dawn ? 0.85 : 0.4
    this.bloom.threshold = dawn ? 0.8 : 0.9
    this.renderer.toneMappingExposure = dawn ? 1.05 : 1.0
    if (this.dew) this.dew.visible = dawn
  }

  /** 截图（视频素材用） */
  snapshot(): string {
    this.composer.render()
    return this.renderer.domElement.toDataURL('image/png')
  }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.frame)
    this.resizeObserver.disconnect()
    this.timer.dispose()
    const el = this.renderer.domElement
    el.removeEventListener('pointermove', this.onPointerMove)
    el.removeEventListener('pointerdown', this.onPointerDown)
    el.removeEventListener('pointerup', this.onPointerUp)
    el.removeEventListener('pointerleave', this.onPointerLeave)
    this.controls.dispose()
    this.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh
      mesh.geometry?.dispose()
      const mat = mesh.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
      else mat?.dispose()
    })
    this.composer.dispose()
    this.renderer.dispose()
    el.remove()
    this.labelRenderer.domElement.remove()
  }

  /* ------------------------------------------------------------------ 布局 */

  private layout(plants: TwinPlant[]) {
    // 有垄号株号的按号摆；缺号的排在最后一垄之后，不丢
    const rows = [...new Set(plants.map((p) => p.row).filter((r): r is number => r != null))].sort((a, b) => a - b)
    const rowIndex = new Map(rows.map((r, i) => [r, i]))
    let maxPos = Math.max(1, ...plants.map((p) => p.pos ?? 0))
    let extra = 0
    const slots = plants.map((p) => {
      if (p.row != null && p.pos != null) return { ri: rowIndex.get(p.row)!, pi: p.pos - 1 }
      const slot = { ri: rows.length + Math.floor(extra / maxPos), pi: extra % maxPos }
      extra += 1
      return slot
    })
    const nRows = Math.max(1, rows.length + Math.ceil(extra / maxPos))
    maxPos = Math.max(maxPos, 1)
    const xHalf = ((nRows - 1) * ROW_GAP) / 2 + ROW_GAP
    const zHalf = ((maxPos - 1) * PLANT_GAP) / 2 + AISLE_MARGIN
    this.bounds = { xHalf, zHalf, roofH: Math.min(5.2, 3.6 + zHalf * 0.12) }
    this.positions = slots.map(({ ri, pi }) => new THREE.Vector3(
      (ri - (nRows - 1) / 2) * ROW_GAP,
      0,
      (pi - (maxPos - 1) / 2) * PLANT_GAP,
    ))
    this.rowCount = nRows
  }
  private rowCount = 1

  private rowX(ri: number) {
    return (ri - (this.rowCount - 1) / 2) * ROW_GAP
  }

  /* ------------------------------------------------------------------ 棚体 */

  /** 棚的横截面（z 从北到南），返回 0–1 参数上的高度 */
  private roofProfile(facility: Facility): (t: number) => THREE.Vector2 {
    const { zHalf, roofH } = this.bounds
    const span = zHalf * 2
    if (facility === 'plastic_tunnel') {
      return (t) => new THREE.Vector2(-zHalf + span * t, 0.3 + (roofH - 0.6) * Math.sqrt(Math.max(0, 1 - (2 * t - 1) ** 2)))
    }
    const wallH = roofH * 0.72
    const ridgeT = 0.16
    return (t) => {
      if (t <= ridgeT) return new THREE.Vector2(-zHalf + span * t, wallH + (roofH - wallH) * (t / ridgeT))
      const u = (t - ridgeT) / (1 - ridgeT)
      return new THREE.Vector2(-zHalf + span * t, 0.5 + (roofH - 0.5) * Math.sqrt(Math.max(0, 1 - u * u)))
    }
  }

  private buildShell(facility: Facility) {
    const { xHalf, zHalf, roofH } = this.bounds
    const pal = this.palette
    const profile = this.roofProfile(facility)
    const SEG = 48
    const accent = new THREE.Color(pal.accent)

    // 地面：深色微反光地坪 + 由近及远淡出的发光网格
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(160, 64),
      new THREE.MeshStandardMaterial({ color: pal.ground, roughness: 0.6, metalness: 0.4 }),
    )
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.03
    ground.receiveShadow = true
    const grid = new THREE.Mesh(
      new THREE.PlaneGeometry(120, 120),
      new THREE.MeshBasicMaterial({
        map: this.gridTexture(accent), transparent: true, opacity: 0.35, depthWrite: false, blending: THREE.AdditiveBlending,
      }),
    )
    grid.rotation.x = -Math.PI / 2
    grid.position.y = -0.02
    // 棚下的底座：略高出地面，四周一圈发光描边
    const padX = xHalf + 0.9
    const padZ = zHalf + 0.9
    const pad = new THREE.Mesh(
      new THREE.BoxGeometry(padX * 2, 0.12, padZ * 2),
      new THREE.MeshStandardMaterial({ color: pal.floor, roughness: 0.5, metalness: 0.35 }),
    )
    pad.position.y = -0.07
    pad.receiveShadow = true
    const padEdge = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-padX, 0, -padZ), new THREE.Vector3(padX, 0, -padZ),
        new THREE.Vector3(padX, 0, padZ), new THREE.Vector3(-padX, 0, padZ),
      ]),
      new THREE.LineBasicMaterial({ color: this.glowColor(accent, 1.6), toneMapped: false }),
    )
    padEdge.position.y = -0.005
    // 扫描环：从棚心向外扩散的一道光，循环
    const scan = new THREE.Mesh(
      new THREE.RingGeometry(0.993, 1, 160),
      new THREE.MeshBasicMaterial({
        color: this.glowColor(accent, 1.3), transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false,
        blending: THREE.AdditiveBlending, toneMapped: false,
      }),
    )
    scan.rotation.x = -Math.PI / 2
    scan.position.y = 0.01
    scan.userData.maxR = Math.hypot(padX, padZ) * 1.8
    this.scan = scan
    this.world.add(ground, grid, pad, padEdge, scan)

    // 棚膜：沿 x 拉伸的曲面，很淡，只留一点反光
    const film = new THREE.BufferGeometry()
    const verts: number[] = []
    const idx: number[] = []
    for (let s = 0; s <= SEG; s++) {
      const p = profile(s / SEG)
      verts.push(-xHalf, p.y, p.x, xHalf, p.y, p.x)
      if (s < SEG) {
        const a = s * 2
        idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2)
      }
    }
    film.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
    film.setIndex(idx)
    film.computeVertexNormals()
    // 粗糙度留高：光滑膜面会把晨光反成一团高光，进辉光后发白
    const filmMat = new THREE.MeshStandardMaterial({
      color: pal.film, transparent: true, opacity: 0.06, roughness: 0.75, metalness: 0, side: THREE.DoubleSide, depthWrite: false,
    })
    this.world.add(new THREE.Mesh(film, filmMat))

    // 山墙（两端）
    const gable = new THREE.Shape()
    gable.moveTo(-zHalf, 0)
    for (let s = 0; s <= SEG; s++) {
      const p = profile(s / SEG)
      gable.lineTo(p.x, p.y)
    }
    gable.lineTo(zHalf, 0)
    const gableGeo = new THREE.ShapeGeometry(gable)
    for (const side of [-1, 1]) {
      const g = new THREE.Mesh(gableGeo, filmMat)
      g.rotation.y = Math.PI / 2
      g.position.x = side * xHalf
      this.world.add(g)
    }

    // 拱架与纵向拉杆：金属细杆；两端山墙拱和屋脊、檐口画发光轮廓
    const frameMat = new THREE.MeshStandardMaterial({ color: pal.frame, metalness: 0.7, roughness: 0.3, transparent: true, opacity: 0.55 })
    const ribCount = Math.max(2, Math.round((xHalf * 2) / 2.4))
    const ribPts = Array.from({ length: SEG + 1 }, (_, s) => profile(s / SEG))
    for (let r = 0; r <= ribCount; r++) {
      const x = -xHalf + (xHalf * 2 * r) / ribCount
      const curve = new THREE.CatmullRomCurve3(ribPts.map((p) => new THREE.Vector3(x, p.y, p.x)))
      const rib = new THREE.Mesh(new THREE.TubeGeometry(curve, SEG, 0.025, 6), frameMat)
      rib.castShadow = true
      this.world.add(rib)
    }
    for (const t of [0.35, 0.55, 0.75]) {
      const p = profile(t)
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, xHalf * 2, 6), frameMat)
      bar.rotation.z = Math.PI / 2
      bar.position.set(0, p.y, p.x)
      this.world.add(bar)
    }
    const glowLine = new THREE.LineBasicMaterial({ color: this.glowColor(accent, 1.5), toneMapped: false })
    for (const x of [-xHalf, xHalf]) {
      this.world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(ribPts.map((p) => new THREE.Vector3(x, p.y, p.x))), glowLine))
    }
    for (const t of [0, facility === 'solar_greenhouse' ? 0.16 : 0.5, 1]) {
      const p = profile(t)
      this.world.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-xHalf, p.y, p.x), new THREE.Vector3(xHalf, p.y, p.x)]),
        glowLine,
      ))
    }

    // 日光温室的后墙（北）：深色墙体，顶边一道发光线
    if (facility === 'solar_greenhouse') {
      const wallH = roofH * 0.72
      const wall = new THREE.Mesh(
        new THREE.BoxGeometry(xHalf * 2 + 0.6, wallH, 0.7),
        new THREE.MeshStandardMaterial({ color: pal.wall, roughness: 0.55, metalness: 0.3 }),
      )
      wall.position.set(0, wallH / 2, -zHalf - 0.35)
      wall.castShadow = true
      wall.receiveShadow = true
      const top = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(-xHalf - 0.3, wallH, -zHalf), new THREE.Vector3(xHalf + 0.3, wallH, -zHalf),
        ]),
        glowLine,
      )
      this.world.add(wall, top)
    }

    // 阴影相机罩住整个棚
    const cam = this.sun.shadow.camera
    const r = Math.max(xHalf, zHalf) + 4
    cam.left = -r
    cam.right = r
    cam.top = r
    cam.bottom = -r
    cam.near = 1
    cam.far = 120
    cam.updateProjectionMatrix()
  }

  /* ------------------------------------------------------------------ 垄与植株 */

  private buildRows() {
    const { zHalf } = this.bounds
    const len = zHalf * 2 - AISLE_MARGIN * 1.2
    const soil = new THREE.MeshStandardMaterial({ color: this.palette.soil, roughness: 0.85 })
    const wire = new THREE.LineBasicMaterial({ color: this.palette.frame, transparent: true, opacity: 0.3 })
    for (let ri = 0; ri < this.rowCount; ri++) {
      const x = this.rowX(ri)
      const ridge = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.16, len), soil)
      ridge.position.set(x, 0.08, 0)
      ridge.receiveShadow = true
      const wireGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x, 2.05, -len / 2), new THREE.Vector3(x, 2.05, len / 2)])
      this.world.add(ridge, new THREE.Line(wireGeo, wire))

      const label = document.createElement('div')
      label.className = 'twin-row-label'
      label.textContent = `第 ${ri + 1} 垄`
      const obj = new CSS2DObject(label)
      obj.position.set(x, 0.2, zHalf - 0.2)
      this.world.add(obj)
    }
  }

  private buildPlants() {
    const n = this.plants.length
    // 吊蔓绳：从垄面拉到顶上的钢丝，黄瓜顺绳往上爬
    const twine = new THREE.InstancedMesh(
      new THREE.CylinderGeometry(0.004, 0.004, 1.9, 4),
      new THREE.MeshStandardMaterial({ color: 0xcfc7a8, roughness: 0.9 }),
      n,
    )
    const stems = new THREE.InstancedMesh(
      new THREE.CylinderGeometry(0.011, 0.02, 1.95, 6),
      new THREE.MeshStandardMaterial({ color: 0x35663a, roughness: 0.75 }),
      n,
    )
    const leafMat = new THREE.MeshStandardMaterial({ map: leafTexture(), roughness: 0.55, metalness: 0.02, side: THREE.DoubleSide })
    // 每片叶一个自发光强度（aGlow），发光色取叶色：异常株亮、健康株基本不亮
    leafMat.onBeforeCompile = (shader) => {
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', 'attribute float aGlow;\nvarying float vGlow;\n#include <common>')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvGlow = aGlow;')
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', 'varying float vGlow;\n#include <common>')
        .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance += vColor.rgb * vGlow;')
    }
    const leaves = new THREE.InstancedMesh(leafGeometry(), leafMat, n * LEAVES)
    this.glowAttr = new THREE.InstancedBufferAttribute(new Float32Array(n * LEAVES), 1)
    leaves.geometry.setAttribute('aGlow', this.glowAttr)
    // 叶柄：从茎节斜伸到叶基
    const petioles = new THREE.InstancedMesh(
      new THREE.CylinderGeometry(0.005, 0.007, 1, 4),
      new THREE.MeshStandardMaterial({ color: 0x4a7d3f, roughness: 0.7 }),
      n * LEAVES,
    )
    const tendrils = new THREE.InstancedMesh(tendrilGeometry(), new THREE.MeshStandardMaterial({ color: 0x8cc163, roughness: 0.6 }), n * 2)
    const flowers = new THREE.InstancedMesh(flowerGeometry(), new THREE.MeshStandardMaterial({
      color: 0xf4cc3a, emissive: 0x5a4300, roughness: 0.5, side: THREE.DoubleSide,
    }), n * 2)
    // 瓜：每株两根垂着的黄瓜，略弯、带一点歪
    const fruits = new THREE.InstancedMesh(
      new THREE.CapsuleGeometry(0.021, 0.2, 4, 8),
      new THREE.MeshStandardMaterial({ color: 0x2f5a26, roughness: 0.5 }),
      n * 2,
    )
    const m = new THREE.Matrix4()
    const q = new THREE.Quaternion()
    const e = new THREE.Euler()
    const one = new THREE.Vector3(1, 1, 1)
    const s = new THREE.Vector3()
    const pos = new THREE.Vector3()
    const node = new THREE.Vector3()
    const dir = new THREE.Vector3()
    const upY = new THREE.Vector3(0, 1, 0)
    this.positions.forEach((p, i) => {
      const seed = this.plants[i].unitId
      const r = hash01(seed)
      const k = 0.9 + r * 0.2
      m.compose(pos.set(p.x + 0.015, 1.1, p.z), q.identity(), one)
      twine.setMatrixAt(i, m)
      m.compose(pos.set(p.x, 0.98 * k, p.z), q.identity(), s.set(1, k, 1))
      stems.setMatrixAt(i, m)
      for (let j = 0; j < LEAVES; j++) {
        const h = (0.3 + (j / (LEAVES - 1)) * 1.55) * k
        const yaw = j * 2.4 + r * 6.283 // 黄金角错开，像真实的互生叶序
        const size = LEAF_SCALE * (1.12 - (j / LEAVES) * 0.42) * (0.9 + hash01(seed * 31 + j) * 0.2)
        const out = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw))
        node.set(p.x, h, p.z)
        // 叶柄斜向上伸出约 12 cm，叶基落在柄端
        const tip = node.clone().addScaledVector(out, 0.1 + 0.03 * hash01(seed + j)).add(new THREE.Vector3(0, 0.07, 0))
        dir.subVectors(tip, node)
        const len = dir.length()
        q.setFromUnitVectors(upY, dir.normalize())
        m.compose(pos.copy(node).add(tip).multiplyScalar(0.5), q, s.set(1, len, 1))
        petioles.setMatrixAt(i * LEAVES + j, m)
        e.set(-Math.PI / 2 - 0.1 - hash01(seed * 7 + j) * 0.3, yaw, (hash01(seed * 11 + j) - 0.5) * 0.4, 'YXZ')
        q.setFromEuler(e)
        m.compose(tip, q, s.set(size, size, size))
        leaves.setMatrixAt(i * LEAVES + j, m)
      }
      for (let j = 0; j < 2; j++) {
        const yaw = r * 6.283 + j * 3.1 + 1.2
        const h = (1.1 + j * 0.55) * k
        // 卷须
        e.set(0, yaw, 0.4)
        q.setFromEuler(e)
        m.compose(pos.set(p.x + Math.sin(yaw) * 0.03, h, p.z + Math.cos(yaw) * 0.03), q, one)
        tendrils.setMatrixAt(i * 2 + j, m)
        // 花：开在叶腋，朝外微仰
        const fy = r * 6.283 + j * 2.2 + 0.6
        e.set(-0.5, fy, 0, 'YXZ')
        q.setFromEuler(e)
        m.compose(pos.set(p.x + Math.sin(fy) * 0.07, (0.95 + j * 0.62) * k, p.z + Math.cos(fy) * 0.07), q, one)
        flowers.setMatrixAt(i * 2 + j, m)
        // 瓜
        const gy = r * 6.283 + j * 2.8
        e.set(0.12 * (hash01(seed + j * 5) - 0.5), gy, 0.18 * (hash01(seed * 3 + j) - 0.3))
        q.setFromEuler(e)
        m.compose(pos.set(p.x + Math.sin(gy) * 0.09, (0.7 + j * 0.45 + r * 0.1) * k, p.z + Math.cos(gy) * 0.09), q, one)
        fruits.setMatrixAt(i * 2 + j, m)
      }
    })
    for (const mesh of [stems, leaves, petioles, fruits]) mesh.castShadow = true
    leaves.receiveShadow = true
    leaves.computeBoundingSphere()
    this.canopy = leaves
    this.paintCanopy()
    this.world.add(twine, stems, petioles, leaves, tendrils, flowers, fruits)
  }

  private paintCanopy() {
    if (!this.canopy) return
    const base = new THREE.Color()
    const c = new THREE.Color()
    const glow = this.glowAttr
    this.plants.forEach((p, i) => {
      base.set(this.palette.state[p.state])
      const g = STATE_GLOW[p.state] + (this.hovered === i ? 0.35 : 0)
      for (let j = 0; j < LEAVES; j++) {
        c.copy(base).offsetHSL(0, 0, (hash01(p.unitId * 13 + j) - 0.5) * 0.08 + (this.hovered === i ? 0.1 : 0))
        this.canopy!.setColorAt(i * LEAVES + j, c)
        // 上层叶亮一点，像从株顶透出来
        glow?.setX(i * LEAVES + j, g * (0.6 + (j / LEAVES) * 0.6))
      }
    })
    if (this.canopy.instanceColor) this.canopy.instanceColor.needsUpdate = true
    if (glow) glow.needsUpdate = true
  }

  private buildPlanMarks() {
    const planned = this.plants.map((p, i) => ({ p, i })).filter(({ p }) => p.list)
    if (planned.length) {
      // 名单色细圈悬在株顶，俯视时不被叶片挡住；确认圈最亮，其余三张名单收淡，免得满屏是圈
      const rings = new THREE.InstancedMesh(
        new THREE.RingGeometry(0.22, 0.25, 48),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }),
        planned.length,
      )
      const m = new THREE.Matrix4()
      const rot = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2)
      const c = new THREE.Color()
      planned.forEach(({ p, i }, k) => {
        const at = this.positions[i]
        const confirm = p.list === 'confirm'
        m.compose(new THREE.Vector3(at.x, 2.25, at.z), rot, new THREE.Vector3(1, 1, 1).multiplyScalar(confirm ? 1.5 : 1.1))
        rings.setMatrixAt(k, m)
        rings.setColorAt(k, c.set(this.palette.task[p.list!]).multiplyScalar(confirm ? 1.6 : 0.7))
      })
      rings.userData.planMark = true
      this.world.add(rings)
    }
    // 推给人确认的株：一根贯通的光柱 + 顶上一颗旋转的菱形标，远看也知道今天要人看哪几株
    const confirm = planned.filter(({ p }) => p.list === 'confirm')
    this.beams = null
    this.markers = null
    this.markerBase = []
    if (confirm.length) {
      const color = this.glowColor(new THREE.Color(this.palette.task.confirm), 1.4)
      const beams = new THREE.InstancedMesh(
        new THREE.CylinderGeometry(0.035, 0.035, 4.6, 10, 1, true),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }),
        confirm.length,
      )
      const markers = new THREE.InstancedMesh(
        new THREE.OctahedronGeometry(0.16, 0),
        new THREE.MeshBasicMaterial({ color: this.glowColor(new THREE.Color(this.palette.task.confirm), 2), toneMapped: false }),
        confirm.length,
      )
      const m = new THREE.Matrix4()
      confirm.forEach(({ i }, k) => {
        const at = this.positions[i]
        m.makeTranslation(at.x, 2.3, at.z)
        beams.setMatrixAt(k, m)
        const base = new THREE.Matrix4().makeTranslation(at.x, 3.35, at.z)
        this.markerBase.push(base)
        markers.setMatrixAt(k, base)
      })
      beams.userData.planMark = true
      markers.userData.planMark = true
      this.beams = beams
      this.markers = markers
      this.world.add(beams, markers)
    }
  }

  /** 风险热力：在株顶上方铺一张模糊过的贴图，高风险偏红；低风险不铺色 */
  private buildHeat() {
    const { xHalf, zHalf } = this.bounds
    const W = 512
    const H = Math.max(64, Math.round((W * zHalf) / xHalf))
    const canvas = document.createElement('canvas')
    canvas.width = W
    canvas.height = H
    const ctx = canvas.getContext('2d')!
    ctx.filter = 'blur(10px)'
    const low = new THREE.Color(this.palette.heatLow)
    const mid = new THREE.Color(this.palette.heatMid)
    const high = new THREE.Color(this.palette.heatHigh)
    const c = new THREE.Color()
    this.plants.forEach((p, i) => {
      if (p.risk == null || p.risk < 0.15) return // 低风险不铺色，热力只标出要留意的地方
      const v = Math.min(1, Math.max(0, p.risk))
      if (v < 0.5) c.copy(low).lerp(mid, v * 2)
      else c.copy(mid).lerp(high, (v - 0.5) * 2)
      const at = this.positions[i]
      const u = ((at.x + xHalf) / (xHalf * 2)) * W
      const w = ((at.z + zHalf) / (zHalf * 2)) * H
      ctx.fillStyle = `rgba(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)},${0.55 + v * 0.45})`
      ctx.beginPath()
      ctx.arc(u, w, ((ROW_GAP * (0.35 + v * 0.45)) / (xHalf * 2)) * W, 0, Math.PI * 2)
      ctx.fill()
    })
    const tex = new THREE.CanvasTexture(canvas)
    tex.colorSpace = THREE.SRGBColorSpace
    const heat = new THREE.Mesh(
      new THREE.PlaneGeometry(xHalf * 2, zHalf * 2),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending }),
    )
    heat.rotation.x = -Math.PI / 2
    heat.position.y = 2.45 // 铺在株顶上方，俯视时不被叶片挡住
    heat.visible = this.heatVisible
    heat.userData.heat = true
    this.heat = heat
    this.world.add(heat)
  }

  /** 清晨棚内的水汽：缓慢漂浮的小点，只在清晨模式显示 */
  private buildDew() {
    const { xHalf, zHalf, roofH } = this.bounds
    const count = 900
    const arr = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      arr[i * 3] = (hash01(i * 3 + 1) * 2 - 1) * xHalf
      arr[i * 3 + 1] = 0.3 + hash01(i * 3 + 2) * (roofH - 0.8)
      arr[i * 3 + 2] = (hash01(i * 3 + 3) * 2 - 1) * zHalf * 0.9
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(arr, 3))
    const dew = new THREE.Points(geo, new THREE.PointsMaterial({
      color: 0xdff3ff, size: 0.07, map: this.dotTexture(), transparent: true, opacity: 0.55, depthWrite: false,
    }))
    dew.visible = this.lightMode === 'dawn'
    this.dew = dew
    this.world.add(dew)
  }

  /* ------------------------------------------------------------------ 巡检车 */

  private makeRover() {
    const group = new THREE.Group()
    const body = new THREE.MeshStandardMaterial({ color: this.palette.rover, metalness: 0.3, roughness: 0.4 })
    const dark = new THREE.MeshStandardMaterial({ color: 0x1b2420, roughness: 0.7 })
    const glow = new THREE.MeshBasicMaterial({ color: this.glowColor(new THREE.Color(this.palette.accent), 1.8), toneMapped: false })
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.2, 0.7), body)
    chassis.position.y = 0.22
    const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.47, 0.03, 0.71), glow)
    stripe.position.y = 0.28
    // 车底一圈地面光晕
    const halo = new THREE.Mesh(
      new THREE.RingGeometry(0.36, 0.44, 48),
      new THREE.MeshBasicMaterial({
        color: this.palette.accent, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending,
      }),
    )
    halo.rotation.x = -Math.PI / 2
    halo.position.y = 0.02
    group.add(chassis, stripe, halo)
    for (const [x, z] of [[-0.25, -0.24], [0.25, -0.24], [-0.25, 0.24], [0.25, 0.24]]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.06, 16), dark)
      wheel.rotation.z = Math.PI / 2
      wheel.position.set(x, 0.1, z)
      group.add(wheel)
    }
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.7, 8), dark)
    mast.position.set(0, 0.67, 0)
    const head = new THREE.Group()
    head.position.set(0, 0.62, 0)
    const cam = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.1, 0.12), body)
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.05, 16), dark)
    lens.rotation.z = Math.PI / 2
    lens.position.x = -0.09
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0 }))
    bulb.position.set(-0.1, 0.07, 0)
    head.add(cam, lens, bulb)
    group.add(mast, head)
    group.traverse((o) => { o.castShadow = true })
    group.scale.setScalar(1.5) // 演示放大，远景里也看得见

    const label = document.createElement('div')
    label.className = 'twin-rover-label'
    label.textContent = '巡检车'
    const tag = new CSS2DObject(label)
    tag.position.set(0, 0.95, 0)
    group.add(tag)
    return { group, head, bulb }
  }

  /** 按计划里要拍的株排路线：逐垄蛇形，过道在垄东侧，换垄时走南端前过道 */
  private buildRoute(order: number[]) {
    const { zHalf } = this.bounds
    const front = zHalf - 1.15
    const dock = new THREE.Vector3(this.rowX(0) - ROW_GAP / 2 - 0.2, 0, front)
    const byUnit = new Map(this.plants.map((p, i) => [p.unitId, i]))
    const stops = order.map((u) => byUnit.get(u)).filter((i): i is number => i != null)
    // 先按所在垄归组，再蛇形
    const rowOf = (i: number) => Math.round(this.positions[i].x / ROW_GAP * 1000)
    const groups = new Map<number, number[]>()
    for (const i of stops) {
      const key = rowOf(i)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(i)
    }
    const rowsSorted = [...groups.keys()].sort((a, b) => a - b)
    const ordered: number[] = []
    rowsSorted.forEach((key, k) => {
      const list = groups.get(key)!.sort((a, b) => this.positions[a].z - this.positions[b].z)
      ordered.push(...(k % 2 === 0 ? list.reverse() : list))
    })

    const segs: Segment[] = []
    let cur = dock.clone()
    let curAisle: number | null = null
    const push = (to: THREE.Vector3) => {
      const d = cur.distanceTo(to)
      if (d > 1e-3) segs.push({ kind: 'move', from: cur.clone(), to: to.clone(), dur: d / ROVER_SPEED })
      cur = to.clone()
    }
    ordered.forEach((i, k) => {
      const p = this.positions[i]
      const aisle = p.x + ROW_GAP / 2
      if (curAisle !== aisle) {
        push(new THREE.Vector3(cur.x, 0, front))
        push(new THREE.Vector3(aisle, 0, front))
        curAisle = aisle
      }
      push(new THREE.Vector3(aisle, 0, p.z))
      segs.push({ kind: 'shoot', plant: i, at: cur.clone(), dur: SHOOT_SECONDS, index: k + 1 })
    })
    push(new THREE.Vector3(cur.x, 0, front))
    push(dock)
    segs.push({ kind: 'dock', at: dock.clone(), dur: DOCK_SECONDS })
    this.segments = segs
    this.roverStops = ordered.length
    this.roverTotal = segs.reduce((sum, s) => sum + s.dur, 0)
    this.roverTime = 0
    this.lastSegment = -1
    this.rover.position.copy(dock)
    this.buildRoutePath(segs)
  }

  /** 计划路线画成贴地光带，光点沿路线流动（方向即行驶方向） */
  private buildRoutePath(segs: Segment[]) {
    const pts: THREE.Vector3[] = []
    for (const seg of segs) {
      if (seg.kind !== 'move') continue
      if (!pts.length) pts.push(seg.from.clone().setY(0.04))
      pts.push(seg.to.clone().setY(0.04))
    }
    this.routePts = pts
    this.routeLen = [0]
    for (let i = 1; i < pts.length; i++) this.routeLen.push(this.routeLen[i - 1] + pts[i].distanceTo(pts[i - 1]))
    this.flowDots = null
    if (pts.length < 2) return
    const accent = new THREE.Color(this.palette.accent)
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: 0.45, depthWrite: false }),
    )
    const dots = new THREE.Points(
      new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(FLOW_DOTS * 3), 3)),
      new THREE.PointsMaterial({
        color: this.glowColor(accent, 2), size: 0.2, map: this.dotTexture(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
      }),
    )
    this.flowDots = dots
    this.world.add(line, dots)
  }

  /** 路线上距起点 d 米处的点 */
  private routeAt(d: number, out: THREE.Vector3) {
    const len = this.routeLen
    let k = 1
    while (k < len.length - 1 && len[k] < d) k += 1
    const seg = len[k] - len[k - 1] || 1
    return out.lerpVectors(this.routePts[k - 1], this.routePts[k], Math.min(1, Math.max(0, (d - len[k - 1]) / seg)))
  }

  private updateRover(dt: number) {
    if (!this.segments.length) return
    if (this.playing) this.roverTime = (this.roverTime + dt) % this.roverTotal
    let t = this.roverTime
    let k = 0
    while (k < this.segments.length - 1 && t > this.segments[k].dur) {
      t -= this.segments[k].dur
      k += 1
    }
    const seg = this.segments[k]
    let flash = 0
    if (seg.kind === 'move') {
      const a = Math.min(1, t / seg.dur)
      this.rover.position.lerpVectors(seg.from, seg.to, a)
      const dir = seg.to.clone().sub(seg.from)
      if (dir.lengthSq() > 1e-6) {
        const yaw = Math.atan2(dir.x, dir.z)
        this.rover.rotation.y = yaw
      }
      this.roverHead.rotation.set(0, 0, 0)
      this.shotRing.visible = false
    } else if (seg.kind === 'shoot') {
      this.rover.position.copy(seg.at)
      // 镜头转向西侧的株：前半段平视拍正面，后半段低头仰拍叶背
      const facing = -this.rover.rotation.y
      const a = t / seg.dur
      this.roverHead.rotation.set(0, facing, a < 0.5 ? 0 : -0.5)
      for (const at of [0.3, 0.8]) {
        const d = Math.abs(a - at)
        if (d < 0.06) flash = Math.max(flash, 1 - d / 0.06)
      }
      const p = this.positions[seg.plant]
      this.shotRing.visible = true
      this.shotRing.position.set(p.x, 0.22, p.z)
      const grow = 1 + a * 1.6
      this.shotRing.scale.set(grow, grow, grow)
      ;(this.shotRing.material as THREE.MeshBasicMaterial).opacity = 0.9 * (1 - a)
    } else {
      this.rover.position.copy(seg.at)
      this.shotRing.visible = false
    }
    ;(this.flashBulb.material as THREE.MeshBasicMaterial).opacity = flash
    this.flash.intensity = flash * 6
    this.flashBulb.getWorldPosition(this.flash.position)

    if (k !== this.lastSegment) {
      this.lastSegment = k
      const status: RoverStatus = { phase: 'moving', unitId: null, index: 0, total: this.roverStops }
      if (seg.kind === 'shoot') {
        status.phase = 'shooting'
        status.unitId = this.plants[seg.plant].unitId
        status.index = seg.index
      } else if (seg.kind === 'dock') {
        status.phase = this.roverStops ? 'docking' : 'idle'
      } else {
        const next = this.segments.slice(k).find((s) => s.kind === 'shoot') as Extract<Segment, { kind: 'shoot' }> | undefined
        if (next) {
          status.unitId = this.plants[next.plant].unitId
          status.index = next.index
        } else status.phase = 'docking'
      }
      this.callbacks.onRover?.(status)
    }
  }

  /* ------------------------------------------------------------------ 交互 */

  private pick(clientX: number, clientY: number): number | null {
    if (!this.canopy) return null
    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1)
    this.raycaster.setFromCamera(this.pointer, this.camera)
    const hit = this.raycaster.intersectObject(this.canopy, false)[0]
    return hit?.instanceId == null ? null : Math.floor(hit.instanceId / LEAVES)
  }

  private onPointerMove = (e: PointerEvent) => {
    const i = this.pick(e.clientX, e.clientY)
    if (i !== this.hovered) {
      this.hovered = i
      this.paintCanopy()
      this.hoverMark.visible = i != null
      if (i != null) this.hoverMark.position.set(this.positions[i].x, 1.1, this.positions[i].z)
      this.renderer.domElement.style.cursor = i != null ? 'pointer' : ''
    }
    this.callbacks.onHover?.(i == null ? null : this.plants[i].unitId, e.clientX, e.clientY)
  }

  private onPointerDown = (e: PointerEvent) => {
    this.downAt = { x: e.clientX, y: e.clientY }
  }

  private onPointerUp = (e: PointerEvent) => {
    if (!this.downAt) return
    const moved = Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y)
    this.downAt = null
    if (moved > 5) return // 拖动视角，不算点击
    const i = this.pick(e.clientX, e.clientY)
    const unitId = i == null ? null : this.plants[i].unitId
    this.select(unitId)
    this.callbacks.onPick?.(unitId)
  }

  private onPointerLeave = () => {
    if (this.hovered != null) {
      this.hovered = null
      this.paintCanopy()
      this.hoverMark.visible = false
    }
    this.callbacks.onHover?.(null, 0, 0)
  }

  /* ------------------------------------------------------------------ 镜头与循环 */

  private fitCamera(animate = false) {
    const { xHalf, zHalf } = this.bounds
    const r = Math.max(xHalf, zHalf * 0.9)
    const target = new THREE.Vector3(0, 0.6, 0.8)
    const pos = new THREE.Vector3(r * 1.45, r * 1.05 + 5, r * 1.75 + 4)
    if (animate) this.tween(target, pos)
    else {
      this.controls.target.copy(target)
      this.camera.position.copy(pos)
      this.controls.update()
    }
  }

  private tweenState: { fromT: THREE.Vector3; toT: THREE.Vector3; fromP: THREE.Vector3; toP: THREE.Vector3; t: number } | null = null
  private tween(target: THREE.Vector3, position: THREE.Vector3) {
    this.tweenState = { fromT: this.controls.target.clone(), toT: target, fromP: this.camera.position.clone(), toP: position, t: 0 }
  }

  private resize() {
    const w = this.container.clientWidth || 1
    const h = this.container.clientHeight || 1
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h)
    this.composer.setPixelRatio(this.renderer.getPixelRatio())
    this.composer.setSize(w, h)
    this.labelRenderer.setSize(w, h)
  }

  private loop = () => {
    if (this.disposed) return
    this.frame = requestAnimationFrame(this.loop)
    this.timer.update()
    const dt = Math.min(this.timer.getDelta(), 0.1)
    const time = this.timer.getElapsed()
    if (this.tweenState) {
      const s = this.tweenState
      s.t = Math.min(1, s.t + dt / 1.2)
      const e = s.t < 0.5 ? 4 * s.t ** 3 : 1 - (-2 * s.t + 2) ** 3 / 2
      this.controls.target.lerpVectors(s.fromT, s.toT, e)
      this.camera.position.lerpVectors(s.fromP, s.toP, e)
      if (s.t >= 1) this.tweenState = null
    }
    this.controls.update()
    this.updateRover(dt)
    if (this.beams) (this.beams.material as THREE.MeshBasicMaterial).opacity = 0.35 + 0.25 * Math.sin(time * 2.4)
    if (this.selectMark.visible) {
      this.selectMark.rotation.y = time * 0.8
      const pulse = 1 + 0.06 * Math.sin(time * 4)
      this.selectMark.scale.set(pulse, 1, pulse)
    }
    if (this.dew?.visible) {
      this.dew.rotation.y = Math.sin(time * 0.05) * 0.02
      ;(this.dew.material as THREE.PointsMaterial).opacity = 0.45 + 0.15 * Math.sin(time * 1.3)
    }
    this.animateTech(time)
    this.composer.render()
    this.labelRenderer.render(this.scene, this.camera)
  }

  /** 科技风的动效：扫描环扩散、确认标旋转浮动、路线光点流动 */
  private animateTech(time: number) {
    if (this.scan) {
      const a = (time % SCAN_SECONDS) / SCAN_SECONDS
      const r = 0.5 + a * (this.scan.userData.maxR as number)
      this.scan.scale.set(r, r, 1)
      ;(this.scan.material as THREE.MeshBasicMaterial).opacity = 0.7 * (1 - a) * Math.min(1, a * 8)
    }
    if (this.markers) {
      const m = new THREE.Matrix4()
      const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), time * 1.6)
      const one = new THREE.Vector3(1, 1.5, 1)
      const pos = new THREE.Vector3()
      this.markerBase.forEach((base, k) => {
        pos.setFromMatrixPosition(base)
        pos.y += Math.sin(time * 2 + k) * 0.08
        this.markers!.setMatrixAt(k, m.compose(pos, q, one))
      })
      this.markers.instanceMatrix.needsUpdate = true
    }
    if (this.flowDots && this.routeLen.length > 1) {
      const total = this.routeLen[this.routeLen.length - 1]
      const attr = this.flowDots.geometry.getAttribute('position') as THREE.BufferAttribute
      const v = new THREE.Vector3()
      for (let i = 0; i < FLOW_DOTS; i++) {
        this.routeAt(((i / FLOW_DOTS) * total + time * 2.2) % total, v)
        attr.setXYZ(i, v.x, v.y, v.z)
      }
      attr.needsUpdate = true
    }
  }

  /* ------------------------------------------------------------------ 工具 */

  /** 圆形柔边的点贴图（默认的点是方块，近看很假） */
  private dotTexture(): THREE.Texture {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 32
    const ctx = canvas.getContext('2d')!
    const g = ctx.createRadialGradient(16, 16, 0, 16, 16, 16)
    g.addColorStop(0, 'rgba(255,255,255,1)')
    g.addColorStop(0.4, 'rgba(255,255,255,0.5)')
    g.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, 32, 32)
    return new THREE.CanvasTexture(canvas)
  }

  /** 提亮到 1 以上的颜色（toneMapped: false 时超出部分进辉光） */
  private glowColor(base: THREE.Color, k: number): THREE.Color {
    return base.clone().multiplyScalar(k)
  }

  /** 地面网格贴图：细线每格、粗线每 5 格，向四周径向淡出 */
  private gridTexture(color: THREE.Color): THREE.Texture {
    const size = 1024
    const cells = 120
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = size
    const ctx = canvas.getContext('2d')!
    const hex = `#${color.getHexString()}`
    for (let i = 0; i <= cells; i++) {
      const v = Math.round((i / cells) * size) + 0.5
      const major = i % 5 === 0
      ctx.strokeStyle = hex
      ctx.globalAlpha = major ? 0.5 : 0.16
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(v, 0); ctx.lineTo(v, size); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(0, v); ctx.lineTo(size, v); ctx.stroke()
    }
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'destination-in'
    const fade = ctx.createRadialGradient(size / 2, size / 2, size * 0.06, size / 2, size / 2, size * 0.5)
    fade.addColorStop(0, 'rgba(0,0,0,1)')
    fade.addColorStop(0.35, 'rgba(0,0,0,0.45)')
    fade.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = fade
    ctx.fillRect(0, 0, size, size)
    const tex = new THREE.CanvasTexture(canvas)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.anisotropy = 4
    return tex
  }

  private makeSelectMark(color: THREE.Color): THREE.Group {
    const g = new THREE.Group()
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.34, 0.42, 48),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95, side: THREE.DoubleSide, depthWrite: false }),
    )
    ring.rotation.x = -Math.PI / 2
    ring.position.y = 0.21
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.4, 0.4, 2.6, 32, 1, true),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }),
    )
    beam.position.y = 1.3
    g.add(ring, beam)
    g.visible = false
    return g
  }

  private gradientTexture(top: THREE.Color, bottom: THREE.Color): THREE.Texture {
    const canvas = document.createElement('canvas')
    canvas.width = 2
    canvas.height = 256
    const ctx = canvas.getContext('2d')!
    const g = ctx.createLinearGradient(0, 0, 0, 256)
    g.addColorStop(0, `#${top.getHexString()}`)
    g.addColorStop(1, `#${bottom.getHexString()}`)
    ctx.fillStyle = g
    ctx.fillRect(0, 0, 2, 256)
    const tex = new THREE.CanvasTexture(canvas)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }

  private clearWorld() {
    this.world.traverse((obj) => {
      const mesh = obj as THREE.Mesh
      mesh.geometry?.dispose()
      const mat = mesh.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose())
      else if (mat) {
        ;(mat as THREE.MeshBasicMaterial).map?.dispose()
        mat.dispose()
      }
      if (obj instanceof CSS2DObject) obj.element.remove()
    })
    this.world.clear()
    this.canopy = null
    this.beams = null
    this.heat = null
    this.dew = null
    this.glowAttr = null
    this.scan = null
    this.markers = null
    this.markerBase = []
    this.flowDots = null
    this.routePts = []
    this.routeLen = []
    this.hovered = null
  }
}
