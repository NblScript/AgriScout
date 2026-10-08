# 架构总览

> 讲清「谁依赖谁、数据怎么流、在哪里扩展」，以及代码注释引用的契约与能力分级。
> 字段级细节看 `docs/generated/db-schema.md`，决策背景看 `docs/design-docs/decision-registry.md`，
> 目标形态（硬件分工、巡检包 v2、部署拓扑）看 `docs/08-system-solution.md`。

## 三层拓扑

```
端（采集）  巡检小车 rover/：Pi 3B 采集编排 + 摄像头/二自由度云台 + 四驱底盘
            模拟器 simulator/：与小车同权的虚拟数据源
              │  HTTP 巡检包协议 v1 / v2 最小子集（合同：GET /api/v1/ingest/patrol-schema）
              ▼
边/云（本仓库）FastAPI backend ←→ SQLite（开发、场边轻量部署）/ PostgreSQL（扩展部署）
            Vue3 frontend：管理台、巡检回放、研究闭环、/screen 展示屏
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
- 研究闭环接在 ⑤ 之后：区域风险预测（D11/D12）→ 复巡与标注任务（D13/D17）→ 随访结论（D10）→
  数据集冻结 → 模型评估闸门（只能绑定已冻结数据集的 test split 审批）。线上复巡生成与离线重放 H2 共用同一联合策略实现（D17）。
- 大棚巡检计划（计划 0015，D18）是另一条入口，接在 ④⑤ 和环境读数之后：

```
温湿度记录仪 CSV ─ rover/env_upload.py ─→ env_readings ─→ greenhouse_env（小时聚合、逐日指标、环境指数、清晨窗口）─┐
株档案 + 叶背照片 + 质量 + 人工确认标注 ─→ plant_state（每株状态：人工优先，模型分占位）──────────────────────┤
                                                                     patrol_planner（planner-v1，纯函数）←┘
                                         → 四张名单写成 revisit_tasks（确认/补拍/全覆盖/抽查）→ 车领任务 / 人在时间线确认
```

  三个计算服务都是纯函数，`greenhouse_plans` 负责取数和落库；计划头存在任务 `parameters` 里，重新生成时作废上一版排队任务。
  离线验证（计划 0017，D21）：`simulator/greenhouse_run.py` 用大棚真值世界通过 HTTP 跑这条链路并导出真值 JSON，
  `services/greenhouse_replay.py` 在同一份真值上逐日调用同一个 `patrol_planner`，与固定巡检同预算比较；模拟结论只证明流程。

## backend 分层与依赖方向（自上而下，禁止反向）

```
api/v1/          薄路由：参数校验、404/422 映射，不含业务逻辑（software_loop.py 的预测与随访部分例外，见技术债）
  ↓ 依赖注入
services/        业务：ingest / analysis / advice / storage / 风险与主动学习 / 评估指标 / 大棚环境与巡检计划
  ↓
models/ + schemas/   ORM 实体 与 DTO/协议（schemas 是对采集端的合同面）
  ↓
core/            config(pydantic-settings) / db(Session) / deps(认证与角色策略，D15) / security(口令哈希、令牌签发)
                 / timeutil(UTC 约定，D9)
```

跨层约定：
- 路由层依赖通过 `Depends()` 注入（get_db / get_analyzer / get_storage / get_session_factory），测试用 `dependency_overrides` 全量替换
- 后台任务不能用请求会话：runner 经 `session_factory` 自建 Session（D2 配套纪律）
- 分析写库合并 crop 名进 detail；建议生成失败不回滚分析结论（延迟 import 隔离）
- 每个分析的点另写 `detail.image_quality`（`iq-rule-v1`，与分析器无关、不改 analyzer_version）；
  车端 `rover/quality.py` 同公式各写一份，由两边同一组合成图测试锁成一致（计划 0016-A）

## 契约

- **巡检包协议 v1 / v2 最小子集**：单一事实源 `app/schemas/patrol.py`，经 `GET /api/v1/ingest/patrol-schema` 导出；
  变更须同步 simulator 与 rover（红线 4）。v2 子集（计划 0014）：点级 `observation_key`（株号）、`route_chainage_m`、
  `distance_source`、`position_source`、`view`（视角、补拍次数、质量），头部 `client_package_id`；出现任一 v2 字段而
  `schema_version` 不是 "2.0" 时 422，v1 包行为不变。其余目标字段见 docs/08 §9。
- **重传幂等**：带 `client_package_id` 时按（设备, 键）判重，内容哈希取规范 JSON 的 SHA-256：同键同内容 200 +
  `duplicate=true` 且不再调度分析，同键异内容 409（detail 带原 `patrol_id`）；不带键仍按「地块 + 设备 + 开始时间」判重。
- **照片分步上传**（计划 0016-B）：`POST /api/v1/media` 收原始图片字节（jpeg/png，≤8MB，新建 201、已有 200，返回
  `{url, sha256, created}`），`GET /api/v1/media/exists?sha256=` 查重；扩展名按魔数定，与包内 base64 照片同一规则，同一份字节
  永远是同一个 URL。巡检包里 `/media/` 开头的照片引用必须已在存储里，否则整包 422；外部 http(s) URL 不校验。rover stops 模式
  先逐张查重上传、再交只含 URL 的 v2 包（内存与照片数无关），200 + `duplicate` 按成功删队列，409 留待人工处理。
- **按计划离线执行**（计划 0016-C）：rover 只读 `GET /fields/{id}/patrol-plans/latest` 和补拍任务的 `parameters.views`，
  离线拍完把每条任务的结果随包排队；包收下后用现有 `PATCH /revisit-tasks/{id}` 先写 `result_note`、再按状态机走到 completed，
  没拍成的只写原因不改状态；确认（label）任务由人关闭，车不回报。后端没有为此改接口。
- **株号关联**：点带株号就落到 `observation_units`（找不到自动建档，`created_from=ingest` 待核对），风险区域键用
  `field-{id}/unit/{株号}`；没有株号回退 D11 网格。邻居只在同类坐标内算，纯网格数据的 risk-lr 输出与改动前逐位一致。
- **Analyzer 协议**（`services/analysis/base.py`）：业务层只依赖它，替换实现零改业务。
  ```python
  class Analyzer(Protocol):
      version: str
      def analyze(self, image: bytes, context: CaptureContext) -> AnalysisResult: ...
  ```
- **规则 YAML**：格式以 `backend/rules/wheat.yaml` 文件头为准（条件键、算子、三层）；生命周期见决策注册表「规则引擎生命周期」。
- **环境读数上报**（计划 0015）：`POST /fields/{id}/env-readings`，`{sensor_key, device?, source?, readings[≤5000]}`；
  同一（地块, 传感器, 时刻）只存一条，重复跳过并计入 `skipped`；不带时区的时间按 UTC（D9），记录仪的当地时间由 `env_upload.py` 先换算。
- **巡检计划任务**：`task_type` 为 label（推给人确认）/ revisit（叶背补拍，`parameters.views` 给多角度序列）/ coverage / random，
  `parameters` 带 `observation_key`、`chainage_m`、`window`（清晨窗口）、`plan_version`、`plan_date`，rationale 带各项分量。

## 关键扩展点

| 扩展点 | 协议 | 当前实现 | 替换方式 |
|---|---|---|---|
| 图像识别 | `Analyzer` | placeholder-color-v0 / YoloAnalyzer（麦穗 + 可选条锈病） | settings `ANALYZER_BACKEND` 分派，业务零改动 |
| 照片存储 | `Storage` | LocalStorage 内容寻址 | 生产换对象存储只改实现类 |
| 规则源 | wheat.yaml | 18 条 | sync-yaml 幂等 upsert，version 自增 |
| 风险模型 | `model_version` | risk-heuristic-v2 / risk-lr-v1（模型文件） | 生成预测时指定版本，D12 |
| 巡检计划 | `PlannerParams` / `DownyMildewEnvParams` | planner-v1 / dm-env-v0（启发式，D18、D22） | 请求里 `overrides` 调参；换策略改 `patrol_planner`，版本号写进每条任务 |
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

- 外壳与视觉（计划 0018）：分组侧栏（工作 / 研究 / 管理）+ 顶栏（面包屑、当前地块切换器、展示屏入口、用户菜单），登录后落脚工作台 `/home`；
  全站浅色，`styles/tokens.css` 是颜色、间距、字号的唯一来源，Element Plus 变量在 `theme.css` 映射到令牌，通用组件在 `components/ui/`
- 管理台：工作台（每个大棚的环境风险、今日计划、株状态分布，待确认、最近巡检）+ 待确认（按株侧滑确认，D20）
  + 大棚详情 `/fields/:id`（概览 / 巡检计划 / 株档案 / 环境 / 巡检记录五个标签页，嵌套路由）+ 单株时间线
  + 巡检回放（按设施类型分大棚按株、大田地图两种模式，问一问 / AI 报告 / 农事建议为折叠分区，D19）
  + 研究闭环（风险/复巡/随访/数据集/模型评估，株号链到单株时间线）+ 地块/作物/种植/设备/用户 CRUD + 系统状态 + 规则修订审批
- `/screen` 展示屏（计划 0018）：工作台的全屏放大版，逐个大棚轮播「垄 × 株」状态网格（PlantGrid）、棚内环境、等人确认，每分钟自动刷新并写明读数时刻
- 数据层：`api/index.ts` 每资源一个 api 对象；类型单一事实源 `types.ts` 对齐 backend schemas
