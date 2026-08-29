import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))

/**
 * /gdmaptiles 缺失必须真实 404（默认 SPA fallback 会把 index.html 当 200 返回，
 * 浏览器把 HTML 缓存成"瓦片"后地图出现灰块）。
 * 不做在线回退：CARTO 已要求 API key、OSM 封锁应用流量，唯一可靠源是本地预缓存
 * （tools/download_tiles.py，高德源 13-18 级）；演示视图由 MapCanvas 的
 * maxBounds/minZoom 钳制在缓存区内。
 */
function tiles404(): Plugin {
  return {
    name: 'tiles-404',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith('/gdmaptiles/') && req.url.endsWith('.png')) {
          const file = resolve(root, 'public', decodeURIComponent(req.url.split('?')[0]).slice(1))
          if (!existsSync(file)) {
            // 命中日志：缺瓦片请求全记录（排查"视图跑出缓存区"的直接证据）
            console.log(`[tiles-404] ${req.url} from ${req.socket.remoteAddress}`)
            res.statusCode = 404
            return res.end('tile not found')
          }
        }
        next()
      })
    },
  }
}

// 开发期把 /api 与 /media(照片) 代理到后端，避免跨域问题
export default defineConfig({
  plugins: [vue(), tiles404()],
  build: {
    // element-plus 全量库单 chunk 必然超默认 500kB，属已知vendor体积（gzip 334kB），阈值调至 1.1MB
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        // 大依赖分包：消 chunk>500kB 告警，且业务代码改动不失效图表/组件库缓存
        manualChunks: {
          echarts: ['echarts'],
          'element-plus': ['element-plus'],
          leaflet: ['leaflet'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

