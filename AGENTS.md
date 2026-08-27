# AGENTS.md — AgriScout 代理地图

农田巡检平台：巡检小车每 0.5m 拍照+采天气 → 平台异步逐点分析（生育期/长势/穗数）→
规则引擎产出可溯源农事建议 → 人工复核标注回流训练集。2027 大挑比赛项目（科技发明 A 类）。

**本文件是地图不是说明书**——约束看红线节，细节按「文档导航」按需读。
所有跨会话知识必须落在仓库文件里，聊天记录等于不存在。

## 命令速查

```bash
# 后端（8000）：venv 用 --without-pip 创建（Python 3.14 无 ensurepip），包装 --target 装依赖
cd backend && .venv/bin/python -m alembic upgrade head
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000
cd backend && .venv/bin/python -m pytest            # 提交前必须全绿

# 前端（5173，/api 代理后端）
cd frontend && pnpm dev                              # 需 export XDG_CACHE/HOME/STATE（见 README）
cd frontend && pnpm typecheck && pnpm build

# 模拟器（一键闭环：建档→采样→上传→分析→建议）
cd simulator && ../backend/.venv/bin/python run.py --scenario dry   # healthy/dry/patchy_disease

# ML 训练（独立环境）
cd ml && .venv/bin/python data/prepare_gwd.py && .venv/bin/python train.py
cd ml && .venv/bin/python export_model.py            # 产物 → backend/models/（gitignore）
```

## 代码地图

| 路径 | 职责 |
|---|---|
| `backend/app/models/` | 12 张表，每实体一文件；`timestamps.py` 公共 mixin |
| `backend/app/api/v1/` | 薄路由层：CRUD + ingest + 分析 + 建议 + 标注 + stats |
| `backend/app/services/analysis/` | Analyzer 协议（base.py）+ 占位颜色版 + YOLO 版 + 后台 runner |
| `backend/app/services/advice.py` | 规则匹配引擎：三层规则（threshold/status/routine）× 六条件六算子 |
| `backend/app/rules/wheat.yaml` | 规则种子库（单一事实源，经 sync_rules 同步入表） |
| `backend/app/schemas/` | DTO + 巡检包协议 v1（对小车端的合同） |
| `backend/migrations/versions/` | 手写 Alembic 迁移，`000N_主题` 命名 |
| `frontend/src/views/` | 七管理页 + PatrolDetailView（回放/复核）+ BigScreenView（/screen 总览） |
| `frontend/src/components/` | MapCanvas（Leaflet 封装，theme=light/dark）、EChart、ScreenPanel |
| `simulator/` | 独立虚拟巡田，只走 HTTP（禁止 import 后端内部） |
| `ml/` | YOLO 训练环境（与后端运行时分离） |

## 不可变红线（违反=返工）

1. **异步分析**：上传请求绝不同步识别照片（2600 张包会超时）——分析走 BackgroundTasks + analysis_status 轮询（D2）
2. **规则单一事实源**：规则改 YAML → sync 入表；Advice 冻结 rule_snapshot，永不回写
3. **照片不进库**：SHA-256 内容寻址存 `media/`，库内只存 URL（D6）
4. **协议即合同**：巡检包 schema 变更必须同步 `/api/v1/ingest/patrol-schema` 导出与模拟器
5. **认证插槽**：无 JWT，全路由挂 `get_current_user` 插槽依赖，不得绕过（B4）
6. **模拟器隔离**：只走 HTTP，禁止 import 后端内部代码（D5）
7. **产物不入库**：`*.db`、`*.pt`、`media/`、`ml/data|runs|.venv` 均 gitignore
8. **测试红线**：backend pytest 全绿才能 commit；协议/引擎改动必须带新测试

## 工作约定

- **里程碑 = commit 单元**，中文消息 `M{n}: 主题——交付物`；文档变更单独 `docs:` 前缀 commit
- **执行计划先行**：非常规改动先在 `docs/exec-plans/active/` 建计划（模板见其 README），
  完成移 `completed/`；决策（编号 D/B/T）登记 `docs/design-docs/decision-registry.md`
- **机械校验**：`backend/tests/test_docs.py` 守护文档新鲜度（链接/行数/db-schema 快照），
  改表结构后运行 `python -m app.tools.gen_db_schema` 重新生成
- **用户偏好**：全中文交流与文档；表格化、克制配色（前端走专业 SaaS 风不走炫酷大屏）

## 文档导航（按需读）

| 何时 | 读 |
|---|---|
| 改数据库 / 看表结构 | `docs/generated/db-schema.md`（生成物，勿手改） |
| 动 Analyzer 或接入新识别模型 | 主计划 §7.2（协议契约）、`services/analysis/base.py` |
| 动规则/建议逻辑 | 主计划 §7.3（YAML 格式）、`services/advice.py`、docs/05 规则生命周期节 |
| 查某个编号决策（D/B/T/L） | `docs/design-docs/decision-registry.md` |
| 理解整体架构 | `ARCHITECTURE.md`（本仓库） |
| 看当前在做什么 / 接手未完工作 | `docs/exec-plans/active/` |
| 立项背景 / 比赛叙事 | docs/01（调研）、docs/07（介绍）、docs/04 §16（三线并行） |
| 硬件 / 小车对接 | docs/04 §9（硬件路线）、docs/06（嵌入式路线） |
