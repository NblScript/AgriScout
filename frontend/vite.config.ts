import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))

// /tiles 瓦片缺失时必须真实 404（Leaflet 据此回退在线源）；
// 默认 SPA fallback 会把 index.html 当 200 返回，破坏本地优先逻辑
function tiles404(): Plugin {
  return {
    name: 'tiles-404',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith('/tiles/') && req.url.endsWith('.png')) {
          const file = resolve(root, 'public', decodeURIComponent(req.url.split('?')[0]).slice(1))
          if (!existsSync(file)) {
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
