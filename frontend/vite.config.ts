import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))

const TILE_HOST = 'basemaps.cartocdn.com' // 唯一回退上游（白名单，无用户可控主机）

/**
 * 瓦片服务：本地 public/tiles 优先；缺失时由 dev server 代理 CARTO 取图。
 * 浏览器只请求 localhost 的 /tiles/*——客户端零回退逻辑、零外部瓦片域名，
 * 从机制上排除 OSM 封锁页/断网灰图（在线回退是服务端行为）。
 *
 * 安全：z/x/y 强制整数并范围断言；上游主机为写死常量；无用户可控 URL。
 */
function tilesProxy(): Plugin {
  return {
    name: 'tiles-proxy',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const m = /^\/tiles\/(\d+)\/(\d+)\/(\d+)\.png$/.exec(req.url?.split('?')[0] ?? '')
        if (!m) return next()
        const [, zs, xs, ys] = m
        const z = Number(zs)
        const x = Number(xs)
        const y = Number(ys)
        const file = resolve(root, 'public', 'tiles', zs, xs, `${ys}.png`)
        if (existsSync(file)) return next() // 命中缓存：交给 vite 静态服务
        if (!(z >= 0 && z <= 19 && x >= 0 && x < 2 ** z && y >= 0 && y < 2 ** z)) {
          res.statusCode = 404
          return res.end('bad tile coords')
        }
        try {
          const upstream = await fetch(`https://${TILE_HOST}/light_all/${z}/${x}/${y}.png`, {
            headers: { 'User-Agent': 'AgriScout-dev-tileproxy/1.0' },
            signal: AbortSignal.timeout(8000),
          })
          if (!upstream.ok) {
            res.statusCode = 404
            return res.end('tile unavailable upstream')
          }
          res.setHeader('Content-Type', 'image/png')
          res.setHeader('Cache-Control', 'public, max-age=86400')
          res.end(Buffer.from(await upstream.arrayBuffer()))
        } catch {
          res.statusCode = 404
          res.end('tile upstream unreachable')
        }
      })
    },
  }
}

// 开发期把 /api 与 /media(照片) 代理到后端，避免跨域问题
export default defineConfig({
  plugins: [vue(), tilesProxy()],
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
