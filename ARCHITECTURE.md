# 架构总览

> 讲清「谁依赖谁、数据怎么流、在哪里扩展」，以及代码注释引用的契约与能力分级。
> 字段级细节看 `docs/generated/db-schema.md`，决策背景看 `docs/design-docs/decision-registry.md`，
> 目标形态（硬件分工、巡检包 v2、部署拓扑）看 `docs/08-system-solution.md`。

## 三层拓扑

```
端（采集）  巡检小车 rover/：Pi 3B 采集编排 + 摄像头/二自由度云台 + 四驱底盘
            模拟器 simulator/：与小车同权的虚拟数据源
              │  HTTP 巡检包协议 v1（合同：GET /api/v1/ingest/patrol-schema）
              ▼
边/云（本仓库）FastAPI backend ←→ SQLite（开发、场边轻量部署）/ PostgreSQL（扩展部署）
            Vue3 frontend：管理台、巡检回放、研究闭环、/screen 总览
            目标部署：Jetson TX2 场边主机同时承载推理服务与轻量平台（docs/08 §4、§7）
训练（离线）ml/ 独立环境，模型经 export_model.py 导出到 backend/models/（不入库）
```

模拟器与小车同权：都只走 HTTP，绝不 import 平台内部代码（D5）。

## 数据流（任务流水线）

```
① 建档 → ② 建任务 → ③ 田间采集 → ④ 接入落库 → ⑤ 异步分析 → ⑥ 建议生成 → ⑦ 回看决策 → ⑧ 复核回流
 田/作物/  巡检/复巡  rover/模拟器  单事务落库 +   逐点分析(D2)   规则匹配 +     地图/时间轴   人工标注 →
 种植/设备 任务        采样          照片内容寻址(D6) analysis_status 快照冻结       采纳/驳回     NDJSON 数据集
```

- 同步段：建档、上传（秒级）、查询、采纳/驳回；异步段：分析（分钟级）、规则匹配、训练与规则修订（天级）。
- 红线：大巡检包（2600 张照片）绝不在上传请求里同步识别；⑥ 完成后才对外发布 `analysis_status=done`。
- 研究闭环接在 ⑤ 之后：区域风险预测（D11/D12）→ 复巡与标注任务（D13）→ 随访结论（D10）→
  数据集冻结 → 模型评估闸门（只能绑定已冻结数据集的 test split 审批）。

## backend 分层与依赖方向（自上而下，禁止反向）

```
api/v1/          薄路由：参数校验、404/422 映射，不含业务逻辑（software_loop.py 例外，见技术债）
  ↓ 依赖注入
services/        业务：ingest / analysis / advice / storage / 风险与主动学习 / 评估指标
  ↓
models/ + schemas/   ORM 实体 与 DTO/协议（schemas 是对采集端的合同面）
  ↓
core/            config(pydantic-settings) / db(Session) / deps(认证插槽) / timeutil(UTC 约定，D9)
```

跨层约定：
- 路由层依赖通过 `Depends()` 注入（get_db / get_analyzer / get_storage / get_session_factory），测试用 `dependency_overrides` 全量替换
- 后台任务不能用请求会话：runner 经 `session_factory` 自建 Session（D2 配套纪律）
- 分析写库合并 crop 名进 detail；建议生成失败不回滚分析结论（延迟 import 隔离）

## 契约

- **巡检包协议 v1**：单一事实源 `app/schemas/patrol.py`，经 `GET /api/v1/ingest/patrol-schema` 导出；
  变更须同步 simulator 与 rover（红线 4）。v2 目标字段（`observation_key`、`route_chainage_m`、`client_package_id` 等）见 docs/08 §9。
- **Analyzer 协议**（`services/analysis/base.py`）：业务层只依赖它，替换实现零改业务。
  ```python
  class Analyzer(Protocol):
      version: str
      def analyze(self, image: bytes, context: CaptureContext) -> AnalysisResult: ...
  ```
- **规则 YAML**：格式以 `backend/rules/wheat.yaml` 文件头为准（条件键、算子、三层）；生命周期见决策注册表「规则引擎生命周期」。

## 关键扩展点

| 扩展点 | 协议 | 当前实现 | 替换方式 |
|---|---|---|---|
| 图像识别 | `Analyzer` | placeholder-color-v0 / YoloAnalyzer（麦穗 + 可选条锈病） | settings `ANALYZER_BACKEND` 分派，业务零改动 |
| 照片存储 | `Storage` | LocalStorage 内容寻址 | 生产换对象存储只改实现类 |
| 规则源 | wheat.yaml | 18 条 | sync-yaml 幂等 upsert，version 自增 |
| 风险模型 | `model_version` | risk-heuristic-v2 / risk-lr-v1（模型文件） | 生成预测时指定版本，D12 |
| 数据库 | SQLAlchemy | SQLite 开发 / PostgreSQL 生产 | DATABASE_URL 切换 + Alembic 迁移 |

## 能力分级

识别线（车上/场边跑的小模型）：

| 级别 | 方案 | 状态 |
|---|---|---|
| L0 | 颜色统计占位 + 日历法生育期 | `placeholder-color-v0`，默认 |
| L1 | 公开数据训练：麦穗检测 wheat-yolo（GWD）、条锈病图块分类 rust-cls（NWRD，D14） | 已实现，可选启用 |
| L2 | 车载自采数据微调 + 场边部署（TX2：ONNX → TensorRT） | 待真车数据（计划 0007 P1-10） |

建议线（规则兜底，LLM 只做解释）：

| 级别 | 方案 | 状态 |
|---|---|---|
| L0 | 规则引擎：作物 × 生育期 × 天气/分析结果 → 可追溯建议 | 已实现 |
| L1 | 规则兜底 + LLM 巡检报告（D7） | 已实现，未配置 LLM 时关闭 |
| L2 | 诊断问答 Agent，只读（D8） | 已实现 |

规则线的「自我优化」另有 L0–L3 分级（决策注册表 L 系列），与上面两条线的编号含义不同。

## 识别引擎版本语义

`Analysis.analyzer_version` 固化每次分析的引擎版本：`placeholder-color-v0`、`yolo-<麦穗模型>`、
`yolo-<麦穗模型>+<病害模型>`，或只配病害模型时 `color+<病害模型>`；历史结果可溯源可复现。
颜色统计（image_color_stats）是各版本共用的底座信号；日历法生育期与胁迫色检出语义跨版本一致，
规则引擎（status 层依赖检出）无需感知引擎切换。

## frontend 结构

- 管理台（Element Plus 亮色）：地块/作物/种植/设备 CRUD + 系统状态 + 规则修订审批 + 研究闭环（风险/复巡/随访/数据集/模型评估）+ 巡检回放（地图/时间轴/复核/建议）
- `/screen` 数据总览：白卡片仪表盘，ECharts 亮色配色，中央 Leaflet 地图（theme 切换）
- 数据层：`api/index.ts` 每资源一个 api 对象；类型单一事实源 `types.ts` 对齐 backend schemas
