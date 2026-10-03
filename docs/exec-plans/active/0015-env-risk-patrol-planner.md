# 0015 · 环境数据 + 每株状态 + 风险驱动巡检计划

## 状态
2026-10-03 建档，同日完成（M15）。总览和共同约定见 [计划 0013](0013-greenhouse-active-acquisition.md)，开工前先读。
批次：第二批。依赖 0014 合并（已完成）（株档案、按株关联、`view` 字段）；可与 0016 阶段 B 并行。迁移号 0016，里程碑 M15。

## 背景
本计划对应创新点三：根据环境风险和每株状态，决定什么时候巡、补拍哪些株、把哪些株推给人确认。同时始终保留随机抽查和低频全覆盖（风险不用来减少巡检）。代码现状：
- 环境数据只有挂在采样点上的 `WeatherSample`，是巡检时刻的快照，没有连续记录。
- `api/v1/software_loop.py` 里的 `generate_revisit_tasks` 把业务逻辑写在路由里。它先按概率截取前 `limit` 条预测再排序，代表性写死 0.5，同一区域会重复入选
  （见技术债台账「线上复巡任务 = 按概率取前 N」）。离线重放的联合策略（`services/offline_replay.py` 的 `h2_revisit_replay` 内部的 `joint`）是另一套实现。
- 标注标签只有 `normal / dry_stress / suspected_disease / other`（`schemas/annotation.py`，注释说与规则引擎的胁迫类别对齐）。
- `RevisitTask` 以 `risk_prediction_id` 唯一；`TaskType` 只有 revisit / label / random。

## 范围
- 做：环境读数的上报、存储和查询；霜霉病环境指标；每株状态；巡检计划生成与落库；旧复巡接口下沉并修技术债；计划页；`rover/env_upload.py`。
- 不做：识别模型（WP5）；rover 执行计划（0016-C）；大棚模拟器（0017）；风险模型训练。

## 设计（已定，照此实现）
1. **表结构**（迁移 0016）：
   - 新建 `env_readings` 表：
     - 列：`id`、`field_id`（外键，CASCADE）、`sensor_key`（String(40)）、`device_id`（外键，SET NULL，可空）、`observed_at`（UTCDateTime）、
       `temp_c`、`humidity_pct`（0–100）、`leaf_wetness`（0–1，可空）、`source`（sensor / import / manual）、`created_at`。
     - 唯一约束 (field_id, sensor_key, observed_at)；索引 (field_id, observed_at)。
   - `revisit_tasks` 加 `observation_unit_id`（外键，SET NULL，建索引）。
2. **上报与查询**：
   - 上报 `POST /fields/{field_id}/env-readings`：
     - 请求体 `{sensor_key, device?: code, source?, readings: [{observed_at, temp_c, humidity_pct, leaf_wetness?}]}`，每次最多 5000 条；
     - 重复的时间戳跳过；返回 `{inserted, skipped}`；
     - 时间不带时区时按 UTC 解释（D9）。
   - 查询 `GET /fields/{field_id}/env?since&until`：返回小时聚合结果和逐日指标。
   - 红线 4 同步：新增 `rover/env_upload.py`，读温湿度记录仪导出的 CSV（列名和时区可通过参数配置），分批上传，只走 HTTP；测试为 `rover/test_env_upload.py`。
     `simulator/client.py` 加一个 `post_env_readings` 方法，供 0017 使用。
3. **环境指标**（新文件 `services/greenhouse_env.py`，纯函数）：
   - 露点用 Magnus 公式（a=17.62，b=243.12）。
   - 小时聚合：温度、湿度均值，最小露点差，读数条数。缺测的小时只标记，不插值。
   - 按田间日期（`field_date`）算逐日指标：
     - `favorable_hours`：15≤T≤25 且 RH≥85 的小时数；
     - `wet_hours`：RH≥95，或 T−Td≤1.0，或 leaf_wetness≥0.5 的小时数；
     - `night_wet_hours`：当地 18:00 到次日 08:00 之间的湿润小时数；
     - `diurnal_range`：日温差；
     - `coverage`：有效小时数 / 24。
   - 环境指数 `env_index` 取近 72 小时：`1 − exp(−(favorable_hours + wet_hours) / 24)`，同时输出各分量。
     如果 72 小时的平均 coverage 低于 0.5，`env_index` 为 None，**不得当成低风险**处理。
   - 清晨窗口：前一夜 `night_wet_hours ≥ 4` 时，建议次日当地 05:30–08:30 做叶背拍摄。
   - 所有阈值放在 `DownyMildewEnvParams` dataclass 里，逐个注释出处（0013「依据」里的农技资料），并标「待农技复核」。
4. **每株状态**（新文件 `services/plant_state.py`，纯函数）：
   - 输入：某株的观测列表（captured_at、side、accepted、risk_score、analyzer_version）和标注列表。
   - 输出：`PlantState{state: healthy/early/symptomatic/unknown, source: human/model/none, confidence, model_score, last_seen_at, last_under_ok_at}`。
   - 人工标注优先，取最近一次。`AnnotationLabel` 新增 `downy_mildew_early`、`downy_mildew_symptomatic`，`normal` 视为健康；
     先查清规则引擎、`rule_feedback`、统计接口对标签的用法，确认新增标签不影响它们。
   - 只有模型结果时：`model_score` 取最近一张合格叶背图的 risk_score；early 和 symptomatic 的阈值做成参数（默认 0.4 / 0.7）；confidence 固定为 0.3。
     注释写明：WP5 之前这只是占位（现有分析器不是黄瓜霜霉病模型）。
   - 没有任何观测时为 unknown。
5. **巡检计划**（新文件 `services/patrol_planner.py`，纯函数，版本号 `planner-v0`）：
   - 输入：全部在用的株（PlantState + 距上次被看到的天数 + 距上次合格叶背图的天数 + 上次叶背质量是否合格 + 邻株最高 model_score）、
     环境输出（env_index、清晨窗口）、参数、随机种子。
   - 输出四张名单（每株最多出现在一张里，优先级：确认 > 补拍 > 全覆盖 > 抽查）和一条时机建议：
     - **确认**：state=early 且来源不是人工，或 model_score ≥ 确认阈值；按分数排序，受人工预算限制（默认每天 5 株）。已经人工确认为明显的株不进这张名单。
     - **补拍**：分数 = w1·model_score + w2·邻株最高分 + w3·env_index（为 None 时取 0.5）+ w4·min(距上次合格叶背天数 / 全覆盖周期, 1)；
       上次叶背质量不合格的再加分。预算按 env_index 在基础比例（默认 10%）和高风险比例（默认 25%）之间插值。
     - **全覆盖**：距上次被看到的天数 ≥ 全覆盖周期（默认 7 天）的株，全部进入。
     - **抽查**：从剩下的株里按固定比例（默认 5%，至少 1 株）随机抽，种子由 (field_id, plan_date) 决定，保证结果可复现。
   - 环境风险低时，全覆盖和抽查名单照样生成。
   - 每条结果都带 `rationale`，写明各项分量和触发原因。
6. **落库与接口**：
   - `POST /fields/{field_id}/patrol-plans`：请求体 `{plan_date?, overrides?, created_by}`。计算后写入 `RevisitTask`：
     - 类型映射：补拍→revisit，确认→label，抽查→random，全覆盖→coverage（`TaskType` 增加 coverage）。
     - 每株每种类型只保留一条未完成任务，已有的就复用并更新 rationale。
     - `parameters` 里写 observation_key、views（补拍时给出叶背多角度序列）、window、plan_version、plan_date。
     - 返回计划全文（包括环境摘要）。
   - `GET /fields/{field_id}/patrol-plans/latest`：取最近一次的计划。
   - `GET /fields/{field_id}/plant-states`：返回各株状态。
   - `/devices/{id}/tasks/next` 的语义不变。
7. **旧复巡接口**：`POST /revisit-tasks/generate` 保留，逻辑下沉到新文件 `services/revisit_planning.py`。
   - 新逻辑：全部 open 预测按 observation_key 去重（每个区域取概率最高的一条），全量参与排序。
   - 把 `joint` 构造候选的代码**原样**提取成共享函数，离线重放和线上都调用它，保证离线结果逐位不变，线上和离线用同一实现。
   - 如果 0016-A 已合并，quality 信号取真实图像质量；否则保持 D13 口径。
   - 技术债台账：「线上复巡任务 = 按概率取前 N」移到「已清」；「software_loop.py 路由层含业务逻辑」注明复巡部分已下沉；
     「复巡任务理由失真」只有在 quality 改用真实质量后才能移到「已清」。
8. **前端**：
   - 地块页对大棚类地块显示「巡检计划」入口，进入 `/fields/:id/plan`（新 `PlanView`）：
     - 环境曲线（EChart）：小时温度、湿度、露点差，再加逐日的适宜时长和湿润时长柱图；
     - 今日计划四张表，原因可展开；「生成计划」按钮只对 operator 及以上角色可用。
   - 0014 的单株时间线页加「确认状态」：选健康 / 早期 / 明显 / 其他，写成标注，挂到该株最近一张合格叶背图上，署名默认填当前用户（沿用 D15 的现状）。

## 验收（测试必须覆盖）
- 环境指标：
  - 露点的已知值；
  - 在构造的数据上，各指标的数值正确；
  - coverage 不足时 `env_index` 为 None，且计划按「无环境信息」处理；
  - 清晨窗口的触发和不触发两种情况。
- 环境上报：幂等；带时区和不带时区的时间；超过上限返回 422；viewer 写入返回 403；`rover/test_env_upload.py` 通过。
- 每株状态：人工优先；模型占位阈值生效；没有数据时为 unknown。
- 巡检计划：
  - env_index 高时补拍名单变长，且给出清晨窗口；
  - env_index 低时，抽查和全覆盖名单仍然非空；
  - 每株只出现在一张名单里；
  - 同样输入加同样种子，结果完全一致；
  - 全覆盖到期的株一定入选；
  - 每条任务的 rationale 都含各项分量。
- 计划接口：重复调用不会重复建任务。
- 旧接口回归：技术债场景（60 个点、13 个区域、取 5 条）选出 5 个不同区域；离线重放 `test_offline_replay` 的现有断言不改动、全部通过；
  对同一输入，线上和离线的选择一致。
- 前端 `pnpm typecheck && pnpm build` 通过。

## 决策记录
- 已定（建档时）：见「设计」1–8。公式和默认参数都是 planner-v0 的启发式，不是训练出来的模型，答辩口径要如实写。执行中的取舍逐条追加在这里。
- 执行中（环境）：
  - 平台按 D9 把不带时区的时间当 UTC；记录仪导出的多是当地时间，所以 `rover/env_upload.py` 按 `--tz`（默认 +08:00）解释后上传带时区的时间。
  - CSV 有坏行时默认整份不上传（打印行号），加 `--skip-bad` 才跳过。静默丢行会让缺测小时看起来像「没有风险」。
  - 同一请求里重复的时刻以第一条为准，与库里已有的一起计入 `skipped`；并发上报撞唯一约束时返回 409，重试即可。
  - `GET /env` 缺省 `until` 取最新读数之后 1 秒（没有读数取当前时间），`since` 取 7 天前，跨度上限 92 天；
    `sensor_key` 可选，缺省时所有传感器一起平均（多记录仪混算记技术债）。
  - 夜间指标归到傍晚那天的田间日期（18:00 到次日 08:00），并单独给出 `night_coverage`；
    清晨窗口看计划日前一夜，前一夜没有数据时改看再前一夜，两夜都没有数据不给窗口。
  - 计划的环境截止时刻取「当前时间」和「计划日当地 08:00」中较早的一个：排当天计划时前一夜已结束，排未来日期时只能算到当前。
- 执行中（每株状态）：
  - 「合格」与 0016-A 同口径：车端 `view.accepted` 优先，没有再看平台测的 `image_quality.ok`；两者都没有时算不确定，不当合格。
  - 人工标签映射：`normal`→健康、`downy_mildew_early`→早期、`downy_mildew_symptomatic`→明显、`other`→不明（看过但不属于三阶段）；
    小麦阶段的 `dry_stress`、`suspected_disease` 不改变每株状态。查过 `rule_feedback`（只统计这两个胁迫标签）、数据集筛选和标注汇总，新增标签不影响它们。
- 执行中（计划）：
  - 人工结论晚于最新照片时，模型分不再触发确认（这批照片已经有人看过）。
  - 人工确认为明显的株除了不进确认名单，也不占补拍预算（设计只写了确认名单）；它们仍会进全覆盖或抽查，保证持续有照片。
  - 补拍预算 = round(比例 × 在册株数)，至少 1 株；环境缺失时按 0.5 插值，与打分一致。抽查株数 = max(1, round(5% × 在册株数))，从前三张名单之外的株里抽。
  - 计划不单独建表：每条名单项写成一条任务，计划头（版本、日期、生成序号、种子、环境摘要）存在任务的 `parameters` 里，「最近计划」按生成序号还原。
  - 重新生成时，上一版里还在排队、这次没入选的计划任务作废（`cancelled`，rationale 记 `superseded_by`），已派给车或执行中的不动。
    这是端到端走查时发现的：不作废的话，旧任务会一直留在 `/devices/{id}/tasks/next` 的队列里，「最近计划」也会混进上一版。
  - 确认任务挂该株最近一张合格叶背图（时间线上的「确认状态」也写在这张上），其余任务挂最近一张照片。
  - 补拍视角序列：叶背 35°/50°/65°、相机离地 0.2 m、补光，待试拍校准。
  - `/devices/{id}/tasks/next` 语义未改。它按优先级取任意排队任务，确认（label）任务也会派给车，记技术债交给 0016-C。
- 执行中（旧复巡接口）：
  - 区域去重取（概率，forecast_start，id）最大的一条；陈旧度按新参数 `patrol_interval_days`（默认 1）的 3 倍归一。
  - 0016-A 已合并，质量信号取本趟该区域照片里合格的比例；没有质量记录的老数据退回 D13 口径。这一口径登记为 D17。
  - 已有测试的改动（未删除、未跳过）：`test_risk_model` 里 risk-lr 复巡任务的用例原先按 D13 断言质量来自模型证据，
    改为断言 `quality_source=image_quality`，用例改名 `test_lr_revisit_tasks_use_measured_quality_not_model_certainty`。
    `test_offline_replay` 断言未改，H2 输出与改动前逐字节一致（快照比对）。
- 执行中（前端）：「确认状态」挂在回看期内最近一张合格叶背图上；回看期内没有时禁用并提示加长回看；只读账号禁用。

## 进度
- [x] 迁移 0016 + 模型 + 重新生成 db-schema
- [x] 环境上报和查询接口、`rover/env_upload.py`、simulator client 方法
- [x] `greenhouse_env`、`plant_state`、`patrol_planner` 三个纯函数及其测试
- [x] 计划接口落库、标签扩展
- [x] 旧复巡接口下沉 + 与离线重放共用实现 + 更新技术债台账
- [x] 前端计划页、时间线页「确认状态」
- [x] 文档：AGENTS 代码地图、ARCHITECTURE（新增服务与环境数据流）
- 验证：backend pytest 286 项全绿；rover / simulator 单测 53 项通过；`pnpm typecheck && pnpm build` 通过；
  在真实前后端上走了一遍（48 株大棚、三趟叶背巡检、10 天记录仪 CSV 经 `env_upload.py` 上传两次，第二次全部跳过；生成计划、时间线确认、重新生成）。
