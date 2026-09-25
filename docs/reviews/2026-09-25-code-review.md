# 代码审查 · 2026-09-25

## 范围与方法

- 范围：`backend/app`（api / services / models / schemas / tools）、迁移、测试、`frontend/src`、`rover/`、`simulator/`。
- 验证：后端 pytest 115 passed；前端 `vue-tsc --noEmit` 与 `vite build` 通过；`rover.test_run_smoke` 9 tests OK。
- 标注为“已复现”的问题都写了临时测试用例并确认失败。这些用例没有提交，修复时应正式补进 `backend/tests/`。

整体评价：分层清晰，红线有代码和测试守护（异步分析、快照冻结、Agent 只读/起草-审批、文档机械校验），错误路径和幂等性考虑得比较周全。
主要风险集中在三处：内容寻址存储的删除语义、规则两条写入通道之间的冲突、设备状态机。

## 严重（建议真车联调前修复）

| # | 位置 | 问题 | 后果 | 建议 |
|---|---|---|---|---|
| 1 | `services/ingest.py` 落库失败清理 | **已复现**。`LocalStorage.save` 按 SHA-256 去重：同一张图已存在时不会再写，但仍返回 URL，`_resolve_photo` 照样把它记为“本次落盘”。落库触发 IntegrityError 回滚时，会把这些 URL 逐一 `storage.delete`。 | 第二个包失败时，会删掉**旧巡检仍在引用**的照片（复现：先成功上传含图 A 的包，再上传含图 A 且落库失败的包，media 目录被清空）。rover 重传、断网补传时正好会上传同一批照片。 | `save` 返回“是否新建”（例如 `(url, created)`），只清理本次真正新建的文件；或者删除前查询 `capture_points.photo_url` 确认没有引用。补一条回归测试。 |
| 2 | `api/v1/device_protocol.py` 心跳 | **已复现**。心跳直接执行 `device.status = payload.status`，而 `status` 默认值是 `idle`。 | 急停、低电压等安全事件把设备置为 `maintenance` 后，下一条默认心跳就会静默恢复成 `idle`，平台可能继续给它派复巡任务。乱序到达的旧心跳也会覆盖新状态。 | 设备处于 `maintenance` 时，心跳不能自动解除，只能通过显式的清除事件或故障注入 `active=false` 解除；只接受 `observed_at` 不早于上一条的心跳去更新状态。 |
| 3 | `tools/sync_rules.py` 对比 `services/rule_revision.py` | 规则有两条写入通道：YAML 同步和修订案审批。审批只写数据库，不回写 YAML；下次 `sync_rules` 时指纹不一致，就会把已批准的修改**覆盖回 YAML 版本**，并且 version 再加 1。 | 人工审批的规则改动会被一次例行同步悄悄撤销，违反“规则单一事实源”红线，建议溯源也会混乱。 | 二选一并登记决策：(a) 审批通过后生成 YAML patch，由人工提交，数据库始终从 YAML 派生；(b) 审批过的规则在表上标记 `origin=revision`，sync 遇到时跳过并报告冲突。 |
| 4 | `services/advice.py` `compute_advice_pairs` | 影子运行使用的纯计算函数**没有**应用“按优先级排序 + 每点 Top-3”截断，而真正生成建议的 `generate_advices_for_patrol` 有。 | 影子 diff 与上线后的实际效果不一致：新增一条 high 规则可能把原有建议挤出 Top-3，影子报告里却显示“无移除”。审批人会依据错误的报告做决定。 | 把排序和 Top-K 抽成共用函数，两处都调用；补一条“新增高优规则挤出旧建议”的影子测试。 |

## 中等

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| 5 | `analysis/runner.py`、`patrols.py` | 进程在分析途中崩溃或重启后，`analysis_status` 会永久停在 `running`：重分析接口返回 409，runner 的原子抢占也不会再成功，没有任何恢复路径。 | 记录 `analysis_started_at`，超时后允许重新抢占；或者在启动时把超时的 `running` 重置为 `error`。 |
| 6 | `models/patrol.py` 与 `services/ingest.py` | 重复上传判重是“先查后插”，数据库没有 `(field_id, device_id, started_at)` 唯一约束，并发重传时可能插入两份巡检。协议里也没有客户端包 ID（rover README 已记录）。 | 巡检包协议 v1.1 增加可选的 `client_package_id`，加上唯一约束；重复时返回 200 和已有的 `patrol_id`，这样 rover 就能安全删除本地队列。 |
| 7 | `api/v1/software_loop.py`（522 行） | 路由层里有大量业务逻辑（预测生成、任务排序与落库、随访状态机）。这与 ARCHITECTURE“api 薄路由，不含业务逻辑”的约定不一致，也最难单独测试。 | 逐步把 `generate_patrol_predictions`、`generate_revisit_tasks`、`upsert_follow_up` 下沉到 service 层，路由只负责映射 HTTP 错误。 |
| 8 | `software_loop.generate_patrol_predictions` | 预测等级为 `unknown`（证据不足）时被强制改成 `low`。 | 与 0005 计划中“缺失或低质量观测不得静默当作健康”的决策相冲突，应保留 `unknown`，或者直接跳过不落库。 |
| 9 | 时间与时区 | `software_loop` 用 `CN_TZ` 生成带时区的时间，但 SQLite 读回的是无时区时间，风险预测的时间窗直接取自 `captured_at`。在 SQLite 和 PostgreSQL 之间切换时，比较和排序的行为可能不一致。 | 统一存 UTC，只在展示层转换为东八区；补一条跨时区的测试。 |
| 10 | 路由里的错误码映射 | `rule_revisions`、`reports`、`agent` 通过判断异常文案是否包含“格式异常”“已存在”来决定返回 502/503/409。 | 改为自定义异常类型（例如 `LLMNotConfigured`、`LLMBadResponse`），避免改一句文案就改变状态码。 |

## 轻微 / 代码卫生

- `services/risk_prediction.py` 自带一个同名的 `RiskPrediction` dataclass，与 ORM 模型重名；另外有 `recheck_window` / `suggested_recheck_time_window` / `recommended_recheck_window` 等多个别名，注释用的是英文。建议改名为 `RiskEstimate`，删掉别名，注释统一为中文。
- `agent_tools` 的 `limit` 参数没有上限，LLM 可以请求超大的 limit。建议统一截断到 50。
- `analysis-summary` 用 `max(versions)` 按字符串取最大的分析器版本，版本号混排时结果不准。
- `sync_rules` 不会停用 YAML 里已经删除的规则，与文档里“只停用不删除”的说法不一致，需要补上停用逻辑，或者修改文档。
- `docs/design-docs/decision-registry.md` 第 88 行的规则路径写成了 `backend/app/rules/wheat.yaml`，实际位置是 `backend/rules/wheat.yaml`。
- 前端 `pinia@4` 有未满足的 peer 依赖（需要 `@vue/devtools-api@^8`）；`element-plus` 的 chunk 约 1MB，可以按需引入。
- 仓库根目录残留 8 个 `.pytest-tmp-*` 目录和 3 个 `.pytest-migration*.db`（都已 gitignore），可以清理。

## 建议修复顺序

1 → 2 → 4 → 3（需要先做出决策）→ 6 → 5，其余并入日常重构。每一项都要带回归测试（测试红线第 8 条）。

## 修复状态（2026-09-25 同日跟进）

| # | 状态 | 做法 | 回归测试 |
|---|---|---|---|
| 1 | 已修复 | `Storage.save_tracked` 返回是否新建；回滚只清理本次新建、且库中无引用的文件；非约束类异常同样回滚并清理 | `test_ingest.py::test_rollback_keeps_photo_shared_with_existing_patrol`、`test_rollback_removes_only_newly_created_photo` |
| 2 | 已修复 | maintenance 为安全锁存：心跳/重新注册不能解除，只能人工在设备管理中修改或清除故障注入；乱序旧心跳只留档不改状态；维护态设备不领取复巡任务 | `test_device_protocol.py::test_safety_lock_not_cleared_by_heartbeat_or_register`、`test_out_of_order_heartbeat_does_not_override_status` |
| 3 | 已修复（方案 b） | sync 发现规则当前版本来自审批修订案且与 YAML 不一致时跳过，并记入 `conflicts`；`--force` 或接口 `?force=true` 以 YAML 覆盖；CLI 遇冲突返回非零 | `test_rule_revision.py::test_yaml_sync_does_not_silently_revert_approved_revision` |
| 4 | 已修复 | 排序与 Top-K 抽为 `_applicable_rules` + `select_top_hits`，建议生成与影子运行共用同一实现 | `test_advice.py::test_shadow_pairs_respect_top_k_like_real_generation` |
| 5 | 已修复 | running 超过 10 分钟无进展（巡检更新时间和最近一次逐点分析时间都早于 10 分钟前）时，重分析接口释放锁并重新调度；正常运行中仍返回 409 | `test_analysis.py::test_stale_running_can_be_reanalyzed_but_fresh_running_is_locked` |
| 8 | 已修复 | 证据不足保留 `unknown`，前端显示为灰色标签 | 现有测试覆盖 |
| 轻微 | 已修复 | agent 工具 `limit` 截断到 50；分析摘要改为取最近一次分析的引擎版本；决策注册表规则路径 | — |
| 6 | 未修 | 需要协议 v1.1（`client_package_id`）、迁移，并同步 simulator/rover，建议单独开执行计划 | — |
| 7、9、10 | 未修 | 重构类（路由下沉 service、统一 UTC、异常类型化），不影响正确性，建议并入后续重构 | — |

## 第二轮复核（2026-09-25 同日）

范围：第一轮修复落地后的工作区（HEAD `f6c57ff` + 未提交修复）。标注“已复现”的问题都写了临时用例并确认失败，修复时已正式补进 `backend/tests/`。

### 第一轮修复带出的问题

| # | 位置 | 问题 | 状态 | 做法 | 回归测试 |
|---|---|---|---|---|---|
| 11 | `tests/test_analysis.py` | 第 5 项的回归测试写成 `from tests.test_ingest import ...`，被 venv 里第三方包自带的顶层 `tests` 遮蔽，全量 pytest 1 failed | 已修复 | 改为与 `from conftest import` 一致的 `from test_ingest import` | 该测试本身 |
| 12 | `device_protocol.py` 故障注入清除 | **已复现**。清除任意注入故障（包括从未注入过的）都会把设备置回 `idle`，真实急停的锁存被一并解除；两个注入故障只清除一个也会解锁 | 已修复 | 锁存规则集中到 `services/device_safety.py`：人工改状态写 `status_override` 事件；清除注入只在「上次人工改状态后无真实安全事件、无其他生效注入、非人工置入维护」时解锁 | `test_device_protocol.py::test_clearing_injected_fault_does_not_release_real_emergency_stop`、`test_clearing_one_fault_keeps_lock_while_another_is_active`、`test_manual_maintenance_survives_fault_clear` |
| 13 | 时间存储（第 9 项的实际后果） | **已复现**。SQLite 丢弃时区存墙钟；rover 上报 `+08:00`，心跳乱序保护把新心跳换算成 UTC 后与库里东八区墙钟比较，后续心跳全被判为旧心跳，设备状态不再更新。原测试只用 `+00:00` 所以没暴露 | 已修复（D9） | 全部时间列改用 `UTCDateTime`，库内一律 UTC、读回带时区；生育期天数按田间时区取日期；巡检列表时间按本地时区显示 | `test_device_protocol.py::test_heartbeat_order_with_cn_timezone`、`test_analysis.py::test_calendar_stage_uses_field_local_date` |
| 14 | `sync_rules.py` 冲突判断 | **已复现**。审批内容回写 YAML 后，冲突判断仍认为规则“来自审批”，此后 YAML 的正常修改被永久挡住（只能 `--force`）；`deactivate` 修订案版本号不变，也会误报冲突 | 已修复 | 迁移 0013 增加 `rule_revisions.yaml_reconciled_at`；sync 发现 YAML 已与审批结果一致时打标并记入 `reconciled`；`deactivate` 不参与内容冲突判断 | `test_rule_revision.py::test_yaml_writeback_reconciles_then_later_edits_sync_normally`、`test_deactivate_revision_does_not_block_yaml_updates` |

### 仍未修复（第一轮未覆盖）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| 15 | `services/agent_chat.py` 兜底分支 | 工具轮次耗尽后删掉全部工具结果再让模型“基于已有信息回答”，回答没有数据依据，但留痕里有一串工具调用，看起来有依据 | 保留 tool 消息，最后一次调用改 `tool_choice="none"` |
| 16 | `frontend/src/api/index.ts` | 采样点只取 `limit=2000`、建议只取 500，`total` 未使用；M7 目标 2600 点会静默截断 | 分页拉取，或为地图提供轻量点位接口 |
| 17 | `schemas/rule.py` `RuleUpdate` | PATCH 不做层级/条件一致性校验；可把 condition 改为 `{}`，空条件命中所有点并挤占 Top-3 | PATCH 时用合并后的规则跑一遍 `RuleCreate` 校验 |
| 18 | `services/llm_report.py` `latest_prompt` | prompt 版本按字符串排序，v10 会被当成比 v2 旧 | 按版本号数值排序 |
| 19 | `api/v1/software_loop.py` 风险生成 | 每点只传入 1 个观测，趋势恒为 `unknown`，复巡任务的“变化”信号恒为 0 | 传入同一点位的历史巡检观测，或在材料中说明首版不含趋势 |

### 验证

- 后端 pytest：129 passed（Windows venv，`--basetemp` 放系统临时目录）。
- 前端 `vue-tsc --noEmit` 通过。
- 迁移 0013：空 SQLite 升级 → 回滚到 0012 → 再升级通过（Windows 下 alembic CLI 按 GBK 读 `alembic.ini` 会失败，用 Python API 验证；WSL 下可直接用 CLI）。
- 旧开发库里客户端写入的东八区墙钟不会自动迁移，读出会晚 8 小时；演示库建议用模拟器重建。
