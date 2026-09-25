# 决策注册表（Decision Registry）

> 本文件是全部编号决策的**唯一注册点**，永不删档：废弃的决策标 `superseded`，不删除。
> 背景缘由：D 系列原定义随旧版决策日志清理而佚失，但代码注释仍在引用（如 simulator/README 引「基线 D5」），
> 2026-08 从 git 历史（commit `8b54152` 版 docs/05）考古补回。此后编号决策在此登记，防止再次断层。
>
> 记录风格沿用 docs/05 惯例：问题 → 选项 → 权衡 → 结论。

## 编号规则

| 前缀 | 含义 | 状态 |
|---|---|---|
| D | 工程决策（实现层） | 启用中，新决策顺延编号 |
| B | 开发基线（架构级拍板） | 启用中，见 docs/05「开发基线定稿」 |
| T | 硬件线技术决策点 | 启用中，多数未决（docs/05） |
| L | 自我优化分级（双飞轮） | 固定 L0–L3，L3 明确不做 |

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
  - L3（自主生效/无人审批）维持 docs/05 的「明确不做」
- **落点**：services/agent_chat.py、agent_tools.py、rule_feedback.py、
  agent_rule_draft.py、shadow_run.py、/rule-revisions 审批页、迁移 0007/0008。

### D7 · LLM 建议线接入（2026-08-27）
- **问题**：建议线 L1（主计划 §8.2：规则兜底 + LLM 解释层）如何接入而不破坏可溯源与红线。
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

## B 系列：开发基线（2026-08 定稿，全文见 docs/05「开发基线定稿」）

| 编号 | 决策 | 一句话 |
|---|---|---|
| B1 | 几何存储 | lat/lng 浮点双列 + boundary 存 GeoJSON 文本；PostGIS 真需要时再迁移 |
| B2 | 前端组件库 | Element Plus + Router + Pinia；Leaflet/ECharts 到可视化里程碑才加 |
| B3 | 首批作物 | 小麦；规则 YAML 种子库与模拟器垄行均按小麦实现 |
| B4 | 用户认证 | 砍除 JWT/登录页，全路由挂 `get_current_user` 插槽，未来零改接口 |

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
