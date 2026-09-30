# 决策注册表（Decision Registry）

> 本文件是全部编号决策的**唯一注册点**，永不删档：废弃的决策标 `superseded`，不删除。
> 背景缘由：D 系列原定义随旧版决策日志清理而佚失，但代码注释仍在引用（如 simulator/README 引「基线 D5」），
> 2026-08 从 git 历史（commit `8b54152` 版 docs/05）考古补回。此后编号决策在此登记，防止再次断层。
> 2026-09-29 删除旧文档 docs/04（主计划）、docs/05（讨论日志）时，其中仍被代码引用的基线、规则生命周期与分级
> 已并入本文件（B/T/L 系列、「规则引擎生命周期」）和 ARCHITECTURE.md（契约、流水线、能力分级）。
> 文中「计划 00NN」是执行计划编号，已删除计划的原文取回方式见 `docs/exec-plans/README.md`。
>
> 记录风格：问题 → 选项 → 权衡 → 结论。

## 编号规则

| 前缀 | 含义 | 状态 |
|---|---|---|
| D | 工程决策（实现层） | 启用中，新决策顺延编号 |
| B | 开发基线（架构级拍板） | 启用中，见下文 B 系列 |
| T | 硬件线技术决策点 | 启用中，见下文 T 系列 |
| L | 规则线自我优化分级 | 固定 L0–L3，L3 明确不做，见下文 L 系列 |

新决策流程：讨论定稿 → 追加条目到本文件 → 相关代码注释引用编号。

## D 系列：工程决策

### D1 · 佚失（未考古到定义）
编号被旧文档体系预留，定义未在现存 git 历史中找到。**空闲可复用**——复用时在此登记新定义。

### D2 · 异步分析红线
- **问题**：一次巡检包最多 2600 张照片（1300m 垄长 × 0.5m），同步识别必然请求超时。
- **结论**：上传只落库快速返回；逐点分析走 BackgroundTasks 后台执行；`Patrol.analysis_status`
  （pending/running/done/error）供前端轮询。量大再升级任务队列，当前单进程够用。
- **落点**：`backend/app/services/analysis/runner.py`、ingest 接口。

### D3 · Alembic 迁移
- **问题**：裸 `create_all` 无法演进表结构。
- **结论**：M1 起引入 Alembic；迁移手写（不 autogenerate），命名 `000N_主题`，
  `revision` 即四位序号；mixin 列（created_at/updated_at）在迁移中显式展开。
- **落点**：`backend/migrations/versions/`。

### D4 · 佚失（未考古到定义）
同 D1，空闲可复用。

### D5 · 模拟器独立顶层
- **问题**：模拟器放 backend 内会诱惑直接 import 内部代码，掩盖协议 bug。
- **结论**：`simulator/` 独立顶层目录，**只走 HTTP 调真实 API**，禁止 import 后端内部代码；
  协议 JSON Schema 从后端 schemas 导出（GET /api/v1/ingest/patrol-schema），作为小车端对接合同。
- **落点**：`simulator/README.md`、`simulator/run.py`。

### D6 · 照片内容寻址本地存储
- **问题**：照片进数据库会把库撑爆；裸文件名会冲突。
- **结论**：库内只存 URL；照片按 SHA-256 内容寻址存本地 `media/` 静态挂载；
  `Storage` 协议抽象隔离，生产换对象存储只改实现类。
- **落点**：`backend/app/services/storage.py`、`backend/media/`（gitignore）。

### D8 · Agent 核心化路线（2026-08-28）
- **问题**：Agent（LLM）如何从"解释者"升级为系统核心，且不破坏可溯源与规则兜底根基。
- **结论**：两期落地，权限递进、每期一道闸：
  - **L2 诊断问答**（只读）：6 个 SELECT 工具箱 + function-calling 循环（≤5轮），
    问答与工具调用链落 agent_conversations 表溯源；**只读不写**是绝对红线
  - **L1 规则起草**（起草权）：燃料统计（采纳/驳回率+漏报信号）→ 起草修订案存
    rule_revisions（status=draft）→ 影子运行（savepoint 内存重算新旧规则 diff，
    不污染 advices）→ **人工批准才写规则表（version+1）**；驳回归档留痕
  - L3（自主生效/无人审批）维持「明确不做」（见 L 系列）
- **落点**：services/agent_chat.py、agent_tools.py、rule_feedback.py、
  agent_rule_draft.py、shadow_run.py、/rule-revisions 审批页、迁移 0007/0008。

### D7 · LLM 建议线接入（2026-08-27）
- **问题**：建议线 L1（ARCHITECTURE.md「能力分级」：规则兜底 + LLM 解释层）如何接入而不破坏可溯源与红线。
- **选项权衡**：
  - 官方 SDK（zhipuai/openai 包）：功能全，但多一个重依赖，且绑定单一厂商 ❌
  - OpenAI 兼容 /chat/completions 直连（httpx 已有依赖）：智谱/DeepSeek/通义全兼容，base_url+key+model 全配置化 ✅
  - RAG 向量库：初期结构化数据量小，直接 JSON 上下文塞 prompt 即可，向量库是过度设计（远期语料大了再说）❌
- **结论**：httpx 直连；新表 `patrol_reports`（一巡检一份 upsert，model/prompt_version/input_digest
  冻结溯源）；prompt 模板文件化（`app/services/llm_prompts/report_vN.md`，版本=文件名）；
  LLM 不写规则表（规则起草属规则线 L1，另立项）；生成失败只记日志不影响分析-建议主链路；
  测试强制清空 LLM 配置 + monkeypatch `_chat`，永不外呼。
- **落点**：`services/llm_report.py`、`api/v1/reports.py`、迁移 0006。

### D9 · 时间统一存 UTC（2026-09-25）
- **问题**：SQLite 存 `DateTime(timezone=True)` 时直接丢弃时区、不做换算。采集端（rover/模拟器）
  上报东八区时间，服务端默认值是 UTC，两种墙钟混存后无法比较——心跳乱序保护因此把新心跳全判为旧心跳。
- **选项权衡**：
  - 只在 API 入参统一换算：漏掉服务端自己写入的时间（如 `datetime.now(CN_TZ)`），读回仍无时区 ❌
  - 统一存东八区墙钟：与服务端 UTC 默认值冲突，切 PostgreSQL 时语义再变一次 ❌
  - 数据库边界统一换算（TypeDecorator）：所有写入换算为 UTC、读回一律带 UTC 时区，DDL 不变 ✅
- **结论**：全部时间列用 `UTCDateTime`（`models/timestamps.py`）；API 输出带时区（`...Z`），前端按浏览器本地时区显示；
  按「天」计的农事语义（生育期天数）用田间业务时区取日期（`core/timeutil.field_date`，固定东八区）。
  旧开发库里客户端写入的东八区墙钟不做自动迁移（来源混杂无法可靠判定），演示库用模拟器重建。
- **落点**：`core/timeutil.py`、`models/timestamps.py`、`services/analysis/base.py`、PatrolsView 时间格式化。

### D10 · 随访标签的时间口径（2026-09-25）
- **问题**：随访接口只检查证据引用和状态机，不检查时间。预测窗口还没结束就能记「确认阴性」（实测提前一年也能提交），
  阳性的事件时间可以落在窗口外，`event_confirmed` 也可以与状态相反。这类标签进入评估后，PR-AUC 和 Brier 会系统性偏高或偏低。
- **选项权衡**：
  - 只在前端提示：接口仍可写入错误标签，第三方和脚本绕得过 ❌
  - 阳性一律要求 `event_at`：计算事件级提前量时确实需要，但现有前端流程会立刻不可用，放到采集事件时间的界面改造里再做 ⏳
  - 后端强制最小口径，前端同步禁用按钮 ✅
- **结论**：`confirmed_negative` 要求服务端当前时间已到 `forecast_end`；给了 `event_at` 时必须不早于 `forecast_start`，
  且阳性不得晚于 `forecast_end`；`event_confirmed` 不得与状态矛盾。窗口内证据不足时先记 `pending`/`insufficient`。
- **落点**：`api/v1/software_loop.py::_check_follow_up_timing`、ResearchLoopView「确认阴性」按钮。依据：申报书 8.2。

### D11 · 观察区域关联 v0 与风险基线 v2（2026-09-25）
- **问题**：风险预测每点只看本次观测，`observation_key` 是 `patrol-{id}/point-{seq}`，每次巡检都不一样，
  多日期数据用不上（审查第 19 项）。协议级区域身份（计划 0007 P0-1）要等团队定区域粒度，又会改巡检包协议。
- **选项权衡**：
  - 等协议 v2：时序与离线重放的开发全部阻塞到越冬期后 ❌
  - 服务端按坐标分箱做过渡关联，不改协议；协议提供区域键后以协议值为准 ✅
- **结论**：区域键 `field-{id}/grid{边长}m/{ix}_{iy}`，原点取地块边界外包框西南角，默认 2.5 m（`region_cell_m` 可调）；
  风险预测的本次与历史观测都按区域聚合（视觉风险取区域内最大值），回看 30 天（`history_days`），只取更早的巡检。
  计算方式变了，默认模型版本升为 `risk-heuristic-v2`；v1 的历史结果按版本号区分，不混在一起评估。
  这一关联适用于模拟器和 RTK 级坐标；当前 rover 的坐标是按步长推算的直线，真车数据不能直接套用。
- **落点**：`services/region_association.py`、`services/risk_inputs.py`、`api/v1/software_loop.py`；计划 0008。

### D12 · 可训练风险模型 risk-lr 的发布与使用约定（2026-09-25）
- **问题**：启发式 v2 对首次显症几乎没有预报能力；要上线可训练模型，需要约定特征怎么保持一致、模型文件放哪、怎么防止误用。
- **结论**：
  - 训练与线上共用 `services/risk_features.py`，由一致性测试锁住，避免训练—上线偏差；
  - 模型文件 `RISK_MODEL_DIR/<版本号>.json` 不入库，含训练目标与 SHA-256，加载时校验；版本号按白名单正则校验，防止路径穿越；
    同版本号默认不允许覆盖；
  - 请求的目标事件、窗口 H、网格边长、回看天数与训练时不一致时拒绝（422）；
  - 等级按相对训练患病率划分（≥5 倍为 high，≥2 倍为 medium）；置信度取 |2p−1|；
  - 使用不强制审批，但每条预测的 evidence 记录模型的审批状态，以便追溯；
  - 指标接口的提前量缺省在相同误报负担下计算。
- **落点**：`services/logistic.py`、`risk_features.py`、`risk_model.py`、`app/tools/train_risk_lr.py`、生成预测与指标接口；计划 0009。

### D13 · 复巡任务信号的口径（2026-09-25）
- **问题**：生成复巡任务时把预测置信度当证据质量。risk-lr 的置信度是 |2p−1|，高风险区域因此「质量满分、不确定性为零」，
  被兜底成随机抽查；证据充分、趋势平稳的高风险区域在启发式模型下也会如此。
- **结论**：
  - 任务打分信号分开取：证据质量 = 证据充分度（有效观测次数 × 图像质量，`risk_prediction.evidence_confidence`，
    启发式置信度即此值），不确定性 = 模型自身的不确定性（risk-lr 为 1−|2p−1|）；
  - risk-lr 的风险信号按模型自己的 high 阈值归一（p ÷ 2×high，封顶 1），使 high 等级对应打分中的 risk ≥ 0.5；
  - 分类顺序：证据不足 → 复巡；证据够但模型不确定 → 标注；风险 ≥ 0.5 或趋势上升 → 复巡确认；
    代表性高 → 随机抽查；都不满足按分数兜底。随机抽查只留给低风险、有代表性的候选。
- **落点**：`services/active_learning.py`（分类规则与阈值）、`risk_model.py`（evidence_quality / level_thresholds）、
  `api/v1/software_loop.py`（`_task_signals`）。

### D14 · 病害识别模型的数据来源与输出口径（2026-09-27）
- **问题**：逐点风险分是风险预测、复巡、随访的起点，但此前来自颜色启发式；需要用来源明确的真实田间数据训练病害模型，
  并约定它怎样进入平台而不改协议和规则。
- **结论**：
  - 首个病害模型 `rust-cls-v1` 只用 NWRD v1.0（Zenodo DOI 10.5281/zenodo.21672928，CC-BY-4.0）训练；划分按整图，官方测试集只用于最终评估；
  - 任务为条锈病图块二分类：掩膜换算标签（锈病像素 ≥ 0.5% / 为 0，边界样本不用），推理时照片缩到短边 480、短边切 3 格逐块判断；
  - 启用 `DISEASE_MODEL_PATH` 后输出一条 `stripe_rust` 汇总检出（置信度 = 最高图块概率，附阳性图块框与面积比例），
    逐点风险分改由模型给出；颜色胁迫检出保留为独立类型，不再决定风险分；检出格式不变，规则与协议零改动；
  - 导出必须附测试集评估（无 `eval.json` 拒绝导出），同名 `.json` 说明文件记录数据来源、许可证、指标、SHA-256 与局限。
- **落点**：`ml/data/prepare_nwrd.py`、`ml/train_rust.py`、`ml/eval_rust.py`、`ml/export_model.py`、
  `backend/app/services/analysis/disease_classifier.py`、`yolo_detector.py`；计划 0010。

### D15 · 登录认证与角色权限（2026-09-29）
- **问题**：B4 砍掉登录后接口全开放，答辩与公网演示都无法回答「谁能看、谁能改、结论是谁下的」；插槽设计承诺过「以后只换实现」。
- **结论**：
  - 令牌为标准 JWT 格式、HS256 签名，口令用 `hashlib.scrypt` 加盐哈希，均用标准库实现（不引入新依赖），由测试锁住签名、过期、算法字段与篡改；
    签名密钥 `AUTH_SECRET` 非 dev 环境必填，缺省拒绝启动；令牌有效期 `AUTH_TOKEN_HOURS`（默认 12 小时）；
  - 所有路由仍挂 `get_current_user` 一个依赖，公开白名单只有健康检查与登录，角色策略集中在 `core/deps.py`；
    每次请求回库读用户，停用、改角色立即生效；测试按 OpenAPI 逐个匿名调用全部接口，除白名单外必须 401；
  - 角色三种：admin（全部 + 用户管理）/ operator（业务读写）/ viewer（只读，非 GET 一律 403，仅允许改自己的口令）；
    至少保留一个启用的管理员，不能停用或降级自己；不设默认账号，首个管理员用 `app.tools.create_user` 建；
  - 采集端（simulator、rover）用操作员账号或令牌认证（参数或 `AGRISCOUT_*` 环境变量），首次 401 自动登录并重试；
  - `/media` 照片仍公开（浏览器 `<img>` 无法携带令牌，URL 为内容哈希不可枚举）；复核人、审批人署名仍由前端提交，
    前端默认填当前登录用户姓名——两项记技术债。
- **落点**：`core/security.py`、`core/deps.py`、`models/user.py`、迁移 0014、`api/v1/auth.py`、`api/v1/users.py`、
  `tools/create_user.py`、前端 `stores/auth.ts`、`LoginView`、`UsersView`、路由守卫；计划 0012。

## B 系列：开发基线（2026-08 定稿）

| 编号 | 决策 | 结论 | 备注 |
|---|---|---|---|
| B1 | 几何存储 | lat/lng 浮点双列 + boundary 存 GeoJSON 文本，bbox 用索引范围查询 | PostGIS 只在真需要空间计算时迁移，接口契约不变 |
| B2 | 前端组件库 | Element Plus + Router + Pinia | Leaflet/ECharts 到可视化里程碑才引入（原生封装，不用包装库） |
| B3 | 首批作物 | 小麦；规则 YAML 种子库与模拟器垄行均按小麦实现 | 生育期：出苗→分蘖→拔节→抽穗→灌浆→成熟 |
| B4 | 用户认证 | 砍除 JWT/登录页，全路由挂 `get_current_user` 插槽，未来零改接口 | **superseded：已被 D15 取代**（插槽已接入登录与角色）；Annotation 仍用 `annotator_name` 字符串归属 |

## 规则引擎生命周期（2026-08 定稿，2026-09 补审批回写）

- YAML（git 管）是源，Rule 表是运行时副本；`sync_rules` 按 `rule_key` 幂等 upsert，内容变更 version 自增，
  纪律是**只停用不删行**（YAML 删掉的规则目前不会被自动停用，见技术债）。
- Advice 冻结 `rule_snapshot`（命中时刻的条件、动作、版本），规则改版后历史建议永远可追溯。
- 三层保覆盖：threshold（天气驱动）/ status（分析驱动）/ routine（生育期保底，任何点都有建议，必须无条件）。
- 新规则先影子运行历史巡检出 diff 报告 → 人工批准 → 生效；`active` 开关秒级回滚。
- 审批通过的修订案须回写 YAML，否则 sync 报 conflicts 并跳过（`--force` 以 YAML 覆盖）。
- 每条规则带 `source` 出处（农技资料/规程）；只做小麦，宁少勿滥。
- 落点：`backend/rules/wheat.yaml`、`tools/sync_rules.py`、`services/advice.py`、`services/shadow_run.py`、`services/rule_revision.py`。

## L 系列：规则线自我优化分级（双飞轮：模型线 + 规则线）

| 级别 | 形态 | 状态 |
|---|---|---|
| L0 | 人看统计清单手改 YAML | 已实现 |
| L1 | 系统 + LLM 起草修订案与 diff，人批准才生效 | 已实现（D8） |
| L2 | 已批准规则集定时影子验证后自动生效 | 远期 |
| L3 | 全自动、无人审批 | **不做**（农业不可接受） |

燃料是技术员的日常操作：标注复核 + 建议采纳/驳回。模型线重训必须过评估闸门（新旧同题对比不降才替换 `analyzer_version`）。

## T 系列：硬件线技术决策点（2026-08 立项，2026-09 按申报书更新）

| 编号 | 决策点 | 状态 |
|---|---|---|
| T1 | 车端主控 / 边缘算力 | 已定：Raspberry Pi 3B（车端采集编排）+ Jetson TX2（场边推理与轻量平台），见 docs/08 §5 |
| T2 | 采样定距与区域关联 | 待定：编码器 + 垄头标记，区域按「垄号 + 桩号分段」（计划 0007 P0-1） |
| T3 | 传感器与环境记录 | 待定：连续环境记录由田间气象站或可追溯数据源提供，车上单点读数不替代（计划 0007 P0-4） |
| T4 | 识别算法与推理位置 | 已定方向：YOLOv8n 系小模型；场边 TX2 以 TensorRT 推理（计划 0007 P1-10 待实机验证） |
| T5 | 车—平台通信 | 已定：现场局域网/Wi-Fi，HTTP 巡检包协议，本地队列断网续传 |
| T6 | 平台技术细节 | 已定：见 B 系列与 D2/D3/D5/D6 |

## 其他在档约束（非编号，但同等级别）

- **红线**：2600 张照片的包绝不在上传请求里同步识别（= D2 的表述版）。
- **规则单一事实源**：`backend/rules/wheat.yaml` 是规则源头，规则表由 YAML 同步派生；
  Advice 冻结 `rule_snapshot` 保证历史可溯源。
- **模拟器红旗**：见 D5；simulator/README 开头即此约束。
- **ML 产物不入库**：`ml/data/`、`ml/runs/`、`*.pt` 均 gitignore；模型经 `ml/export_model.py`
  导出至 `backend/models/`（同样 gitignore），模型版本由 `analyzer_version` 字段溯源。

## 决策变更记录

| 日期 | 编号 | 变更 |
|---|---|---|
| 2026-08 | D1–D6 | 原定义随 docs 清理佚失；从 git 考古补回 D2/D3/D5/D6，D1/D4 标记空闲 |
| 2026-08-27 | D7 | 新增：LLM 建议线接入决策（OpenAI 兼容直连 + patrol_reports 溯源设计） |
| 2026-09-25 | D9 | 新增：时间统一存 UTC，农事日期按田间时区（第二轮审查修复，计划 0006） |
| 2026-09-25 | D10 | 新增：随访标签的时间口径（第三轮审查，申报书 8.2） |
| 2026-09-25 | D11 | 新增：观察区域关联 v0（网格分箱）与风险基线 v2（计划 0008） |
| 2026-09-25 | D12 | 新增：可训练风险模型 risk-lr 的发布与使用约定（计划 0009） |
| 2026-09-25 | D13 | 新增：复巡任务信号的口径（risk-lr 高风险区域被归为随机抽查的修复） |
| 2026-09-27 | D14 | 新增：病害识别模型的数据来源与输出口径（计划 0010） |
| 2026-09-29 | D15 | 新增：登录认证与角色权限（计划 0012），取代 B4 |
| 2026-09-29 | B/T/L | 删除 docs/04、05：B 系列补全备注，新增「规则引擎生命周期」、L 系列表、T 系列当前状态 |
