# AgriScout 农田巡检平台

农作物全生命周期管理系统：田间巡检小车每 0.5 米拍照 + 采集天气数据，
平台自动判断作物生长情况并给出农事建议。

## 当前状态：M3 分析管线 ✅

- `backend/` — Python FastAPI 后端（健康检查 + 基础管理 CRUD + 巡检包接入 + 异步分析管线，Alembic 迁移）
- `frontend/` — Vue 3 + TypeScript + Element Plus 前端（系统状态页 + 四个管理页）
- `docs/` — 设计文档（`01` 调研笔记 / `04` 主计划 / `05` 讨论决策日志 / `06` 嵌入式学习路线）
- 架构基线见 `docs/05-discussion-decisions.md`「开发基线定稿」节

## 快速启动

### 后端（端口 8000）
```bash
cd backend
python3 -m venv --without-pip .venv          # 若 venv 可用则 python3 -m venv .venv
python3 -m pip install --target .venv/lib/python3.14/site-packages -r requirements.txt
.venv/bin/python -m alembic upgrade head     # 建表/升级数据库结构
.venv/bin/python -m uvicorn app.main:app --port 8000
```
接口文档：http://localhost:8000/docs

### 前端（端口 5173，/api 自动代理到后端）
```bash
cd frontend
export XDG_CACHE_HOME=$PWD/../.pnpm-cache XDG_DATA_HOME=$PWD/../.pnpm-data XDG_STATE_HOME=$PWD/../.pnpm-state
pnpm install
pnpm dev
```
访问：http://localhost:5173

### 测试
```bash
cd backend && .venv/bin/python -m pytest
```

### 巡检包上传（M2 数据接入，采集端唯一入口）
```bash
curl -X POST http://localhost:8000/api/v1/ingest/patrol \
  -H 'Content-Type: application/json' -d @patrol_package.json
# patrol.photo 支持 base64 或 URL；单包单事务；照片按内容哈希存 backend/media/
# 上传后后台自动逐点分析（占位=颜色统计估长势+日历法推生育期）
# 查询：GET /api/v1/patrols、/api/v1/patrols/{id}、
#       /api/v1/capture-points?patrol_id=&bbox=minLng,minLat,maxLng,maxLat&limit=&skip=
# 分析：GET /api/v1/patrols/{id}/analysis-summary、POST /api/v1/patrols/{id}/analyze(重分析)
```

### 生产数据库（可选）
```bash
docker compose up -d postgres
# backend/.env 中设置 DATABASE_URL=postgresql+psycopg://agriscout:agriscout@localhost:5432/agriscout
```
