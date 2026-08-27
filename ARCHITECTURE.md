# 架构总览

> 端-边-云三层；本文讲清「谁依赖谁、数据怎么流、在哪里扩展」。
> 字段级细节看 `docs/generated/db-schema.md`，决策背景看 `docs/design-docs/decision-registry.md`。

## 三层拓扑

```
┌─ 端（采集）──────────┐   HTTP 巡检包协议 v1    ┌─ 云（本仓库）─────────────────┐
│ 巡检小车 / 模拟器      │ ─────────────────────→ │ FastAPI backend  ←→ SQLite/PG │
│ RK3588 + 编码器定距拍照 │ ←───────────────────── │ Vue3 frontend（管理/回放/总览） │
│ 未来：端侧量化 YOLO(L2) │   GET patrol-schema     │ ml/ 训练环境（离线）           │
└──────────────────────┘   （对接合同）           └───────────────────────────────┘
```

模拟器与小车同权：都只走 HTTP，绝不 import 平台内部代码（D5）。

## 数据流（八阶段任务流水线）

```
建档(田/作物/种植/设备) → 巡检包上传(单事务落库) → 照片内容寻址存储(D6)
  → 后台逐点分析(D2, analysis_status 轮询) → 建议自动生成(规则匹配+快照冻结)
  → 地图回放/时间轴 → 建议采纳/驳回(决策保护) → 人工复核标注 → NDJSON 训练集导出(回流闭环)
```

## backend 分层与依赖方向（自上而下，禁止反向）

```
api/v1/          薄路由：参数校验、404/422 映射，不含业务逻辑
  ↓ 依赖注入
services/        业务：ingest(落库) / analysis(管线) / advice(引擎) / storage(协议)
  ↓
models/ + schemas/   ORM 实体 与 DTO/协议（schemas 是对小车端的合同面）
  ↓
core/            config(pydantic-settings) / db(Session) / deps(认证插槽)
```

跨层约定：
- 路由层依赖通过 `Depends()` 注入（get_db / get_analyzer / get_storage / get_session_factory），测试用 `dependency_overrides` 全量替换
- 后台任务不能用请求会话：runner 经 `session_factory` 自建 Session（D2 配套纪律）
- 分析写库合并 crop 名进 detail；建议生成失败不回滚分析结论（延迟 import 隔离）

## 关键扩展点

| 扩展点 | 协议 | 当前实现 | 替换方式 |
|---|---|---|---|
| 图像识别 | `Analyzer`（base.py，主计划 §7.2） | placeholder-color-v0 / YoloAnalyzer | settings `ANALYZER_BACKEND` 分派，业务零改动 |
| 照片存储 | `Storage` | LocalStorage 内容寻址 | 生产换对象存储只改实现类 |
| 规则源 | YAML 结构（主计划 §7.3） | wheat.yaml 18 条 | sync-yaml 幂等 upsert，version 自增 |
| 数据库 | SQLAlchemy | SQLite 开发 / PostgreSQL 生产 | DATABASE_URL 切换 + Alembic 迁移 |

## 识别引擎版本语义

`Analysis.analyzer_version` 固化每次分析的引擎版本（placeholder-color-v0 / yolo-wheat-yolo-vN），
历史结果可溯源可复现；颜色统计（image_color_stats）是占位版与 YOLO 版共用的底座信号；
日历法生育期与胁迫色检出语义跨版本一致——规则引擎（status 层依赖 stress 检出）无需感知引擎切换。

## frontend 结构

- 管理台（Element Plus 亮色）：七页 CRUD + 巡检回放（地图/时间轴/复核/建议）
- `/screen` 数据总览：白卡片仪表盘，ECharts 亮色配色，中央 Leaflet 地图（theme 切换）
- 数据层：`api/index.ts` 每资源一个 api 对象；类型单一事实源 `types.ts` 对齐 backend schemas
