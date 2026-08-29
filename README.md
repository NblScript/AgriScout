# AgriScout 农田巡检平台

农作物全生命周期管理系统：田间巡检小车每 0.5 米拍照 + 采集天气数据，
平台自动判断作物生长情况并给出农事建议。

> AI 代理协作入口：[AGENTS.md](AGENTS.md)（代理地图）· [ARCHITECTURE.md](ARCHITECTURE.md)（架构）·
> docs/design-docs/decision-registry.md（决策注册表）· docs/exec-plans/（执行计划）。

## 当前状态：M6 可视化 ✅ + 标注回流闭环 ✅ —— 软件线 M0–M6 全部完成

- `backend/` — Python FastAPI 后端（基础管理 + 数据接入 + 分析管线 + 规则建议引擎 + 人工标注回流，Alembic 迁移）
- `frontend/` — Vue 3 + TypeScript + Element Plus + Leaflet（管理页 + 巡检任务列表 + 地图回放/时间轴/建议面板 + 人工复核标注）
- `simulator/` — 独立虚拟巡田模拟器（一键：建档→S形采样→合成照片→上传→分析→建议闭环报告）
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
数据总览（演示用，亮色仪表盘）：http://localhost:5173/screen

### 一键虚拟巡田（M5 模拟器）
```bash
cd simulator && ../backend/.venv/bin/python run.py --scenario dry
# 场景：healthy / dry / patchy_disease；自动建档→采样→上传→等待分析→打印建议报告
# 协议对接合同（给小车端）：GET http://localhost:8000/api/v1/ingest/patrol-schema
```

### 测试
```bash
cd backend && .venv/bin/python -m pytest
```

### YOLO 麦穗检测（M-AI 识别线 L1，公开数据集训练）
```bash
# 训练环境（独立于后端，含 torch/CUDA 约 5GB）
cd ml && python3 -m venv --without-pip .venv
python3 -m pip install --target .venv/lib/python3.14/site-packages -r requirements.txt

# 数据 → 训练 → 导出（有 GPU 自动用 GPU；无 GPU 加 --max-images 1500 减量）
.venv/bin/python data/prepare_gwd.py            # Global Wheat Head → YOLO 格式
.venv/bin/python train.py --epochs 40           # 产物 runs/wheat-v1/weights/best.pt
.venv/bin/python export_model.py                # → backend/models/wheat-yolo-v1.pt

# 后端切换识别引擎（backend/.env）
#   pip install -r requirements-ml.txt         # backend venv 装推理依赖
#   ANALYZER_BACKEND=yolo
#   YOLO_MODEL_PATH=./models/wheat-yolo-v1.pt
# 切回颜色统计占位：ANALYZER_BACKEND=placeholder（默认，零依赖）
# analyzer_version 记录引擎与模型版本，历史分析结果可溯源可复现
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
# 建议：分析完成后自动生成（可溯源 rule_snapshot）；
#       GET /api/v1/patrols/{id}/advices、PATCH /api/v1/advices/{id}(采纳/驳回)
# 规则：GET|POST|PATCH|DELETE /api/v1/rules（删除=软下线）；POST /api/v1/rules/sync-yaml
#       或命令行同步：cd backend && .venv/bin/python -m app.tools.sync_rules
# 标注回流（M6+ 人工复核，前端回放页可直接操作）：
#   POST   /api/v1/capture-points/{id}/annotations        （同点同标签幂等 upsert）
#   GET    /api/v1/capture-points/{id}/annotations
#   GET    /api/v1/patrols/{id}/annotations[/summary]     （列表 / 进度汇总）
#   PATCH|DELETE /api/v1/annotations/{id}                 （修正 / 撤回）
#   GET    /api/v1/annotations/export?patrol_id=          （NDJSON 训练集导出，
#                                                          含照片URL+人工标签+机器分析快照，供 YOLOv8n 消费）
# 大屏：GET /api/v1/stats/overview（资源计数+建议分布+近5次巡检摘要，指挥大屏单请求数据源）
```

### 离线地图瓦片（演示防断网）
```bash
python3 tools/download_tiles.py --lat 39.1003 --lng 116.1003   # 高德源，含 GCJ-02 换算
# 底图唯一源 = 本地高德瓦片 /gdmaptiles（13-18 级，约 10MB）；无在线回退，
# 视图被 minZoom/maxBounds 钳制在缓存区内。更换演示田重跑脚本即可。
```

### AI 农事报告（建议线 L1：规则兜底 + LLM 解释层）
```bash
# backend/.env 配置任一 OpenAI 兼容端点（智谱/DeepSeek/通义等）：
#   LLM_API_BASE=https://open.bigmodel.cn/api/paas/v4
#   LLM_API_KEY=你的key
#   LLM_MODEL=glm-4-flash
# 巡检分析完成后自动生成；手动：POST /api/v1/patrols/{id}/report/generate
#   查询：GET /api/v1/patrols/{id}/report（前端回放页"AI 农事报告"面板）
# 未配置则功能静默关闭，主链路不受影响；报告冻结 model/prompt/输入摘要可溯源
```

### AI Agent（建议线 L2 + 规则线 L1）
```bash
# 诊断问答（回放页「问一问」面板）：
#   POST /api/v1/agent/chat {"question": "...", "patrol_id": 7}
#   Agent 只读查询平台数据（function-calling ≤5轮），每问留痕可溯源
# 规则进化（侧栏「规则修订审批」页）：
#   GET  /api/v1/rule-feedback                    （规则健康度：采纳/驳回率+漏报信号）
#   POST /api/v1/rule-revisions/generate          （Agent 起草修订案，仅起草）
#   POST /api/v1/rule-revisions/{id}/shadow       （影子运行：新旧规则 diff）
#   POST /api/v1/rule-revisions/{id}/approve|reject（人工批准才写入规则表 version+1）
# 双红线：L2 只读不写；L1 起草权与生效权分离（影子+人工两道闸）
```

### 生产数据库（可选）
```bash
docker compose up -d postgres
# backend/.env 中设置 DATABASE_URL=postgresql+psycopg://agriscout:agriscout@localhost:5432/agriscout
```
