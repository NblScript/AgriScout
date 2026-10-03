# 0014 · 按株建档 + 巡检包协议 v2 最小子集 + 单株时间线

## 状态
2026-10-03 建档，未开工。总览和共同约定见 [计划 0013](0013-greenhouse-active-acquisition.md)，开工前先读。
批次：第一批，可与 0016 阶段 A 并行。迁移号 0015，里程碑 M14。

## 背景
本计划是创新点二「同株时序追踪」的地基：每天拍的照片要能对到同一株上。代码现状如下：
- 巡检包 v1（`backend/app/schemas/patrol.py`）每个点只有 `seq / distance_m / lng / lat / captured_at / photo / weather`，没有株号、视角和行内位置。
- 跨日期关联靠 D11 的 2.5 m 网格（`services/region_association.py`）。rover 的坐标是按步长推出来的一条直线，所以网格关联对真车无效。
- 重复上传按「地块 + 设备 + 开始时间」判重，一律返回 409（`services/ingest.py`）；rover（`rover/run.py` 的 `upload_with_retry`）收到 409 后不会删除本地队列，只能人工处理。
- 风险输入（`services/risk_inputs.py` 的 `build_region_series`）按网格键聚合；`services/risk_model.py` 的 `image_table` 用 `parse_key` 取网格坐标来算邻居，不是网格键的点就没有邻居。
- 目标协议见 docs/08 §9.3，本计划只实现其中的最小子集（取舍见 0013 的决策记录）。

## 范围
- 做：株档案表与接口；协议 v2 的最小子集字段；`client_package_id` 幂等；按株号做跨日关联（没有株号时回退到网格）；单株时间线接口和前端页面；模拟器 `--v2` 选项。
- 不做：坐标可空；docs/08 的其余 v2 字段；rover 改造（0016-B）；每株状态和巡检计划（0015）；照片分步上传（0016-B）。

## 设计（已定，照此实现）
1. **株档案表 `observation_units`**：
   - 列：`id`、`field_id`（外键，CASCADE）、`key`（String(80)，株号）、`row_no`、`position_no`（Integer，可空）、
     `chainage_m`（Float，可空，标称行内位置）、`tag_code`（String(80)，可空）、`status`（active / retired）、
     `created_from`（manual / bulk / ingest）、`note`、时间戳。
   - 唯一约束：(field_id, key)、(field_id, tag_code)。
   - 键符合推荐格式 `R{nn}-P{nnn}` 时自动解析出 row_no / position_no。
   - `fields` 表加 `facility_type`（open_field / solar_greenhouse / plastic_tunnel，可空；旧数据为空，视为 open_field）。
2. **表结构变更**：
   - `capture_points` 加可空列：`observation_key`（String(80)，建索引）、`observation_unit_id`（外键，SET NULL，建索引）、
     `route_chainage_m`（Float）、`distance_source`（String(20)）、`position_source`（String(20)）、`view_meta`（JSON；协议字段名是 `view`，库里换个列名避开关键字）。
   - `patrols` 加：`schema_version`（String(8)，默认 "1.0"）、`client_package_id`（String(64)，可空）、`package_sha256`（String(64)，可空），
     以及唯一约束 (device_id, client_package_id)。
   - 迁移 0015 手写，带 downgrade。
3. **协议**（`schemas/patrol.py`）：
   - 包级字段：`schema_version: Literal["1.0","2.0"] = "1.0"`。
   - 头部字段：`client_package_id`（1–64 位，`^[A-Za-z0-9_.:-]+$`）。
   - 点级字段：
     - `observation_key`；
     - `route_chainage_m`（≥0）；
     - `distance_source`（encoder / odometry / configured / estimated）；
     - `position_source`（rtk / gnss / tag / encoder / estimated / manual）；
     - `view`：`ViewPayload`，字段按 0013 共同约定定义；其中 `quality` 写成宽松的 dict，只校验 `ok` 必须是 bool。
   - 只要出现任一 v2 字段而 `schema_version` 不是 "2.0"，就返回 422，提示升级。v1 包的行为完全不变。
4. **幂等**：
   - 带 `client_package_id` 时，先按 (device, key) 查已有巡检：
     - 查不到：正常落库，原有的三元组判重照样生效，冲突仍返回 409；
     - 查到且内容哈希相同：返回 **200**，`IngestResultOut.duplicate=true`，并带回原 `patrol_id`，不再调度分析；
     - 查到但哈希不同：返回 409，`detail` 里写明已有的 `patrol_id`。
   - 内容哈希取校验后包的规范 JSON：`model_dump(mode="json")`，`sort_keys`，紧凑分隔符。
   - 并发插入撞上唯一约束（IntegrityError）时，重新查一次再走上面的逻辑。新包仍返回 201。
5. **株号落库**：ingest 时按 (field_id, observation_key) 找株档案。找不到就自动建档（`created_from="ingest"`），以免丢数据；在列表页能筛出这类档案，供人工核对。
6. **按株关联**（`risk_inputs.py`、`risk_model.py`）：
   - 有 `observation_unit_id` 的点，区域键用 `field-{fid}/unit/{key}`；没有的继续用网格键。
   - `RegionInputs` 新增 `coords: dict[str, tuple[str, int, int]]`，第一位是类型（`grid` 或 `unit`）：网格键填格子坐标，株键填 (row_no, position_no)。
   - `image_table` 改用 `coords`，不再调用 `parse_key`。邻居只在同一类型之间计算（同类型内仍是 8 邻域，对株而言就是同垄 ±1 株加相邻垄），两类坐标不得混在一个 `neighbor_map` 里。
   - 只有网格数据时，risk-lr 的输出必须与改动前逐位一致。
7. **接口**（新路由文件 `api/v1/observation_units.py`，挂在 v1 下；权限沿用 `get_current_user`）：
   - `GET /fields/{field_id}/observation-units`：可按 `row_no`、`status`、`created_from` 筛选；`POST` 同路径建单株。
   - `POST /fields/{field_id}/observation-units/bulk`：请求体 `{rows: [{row_no, plants, spacing_m, start_chainage_m}]}`，
     按推荐格式生成键；幂等，已有的跳过；返回 created 和 skipped 两个计数。
   - `PATCH /observation-units/{id}`：可改 tag_code、status、note。
   - `GET /observation-units/{id}/timeline?days=30`：
     - 返回 `{unit, days: [{field_date, photos: [...], annotations: [...], predictions: [...]}]}`，日期升序，`field_date` 用 `core/timeutil.field_date`。
     - photos 每项含 capture_point_id、patrol_id、captured_at、photo_url、view，以及 analysis（risk_score、disease_detections、analyzer_version，
       另有 `detail.image_quality`，0016-A 合并后才有，没有就返回 null）。
     - predictions 每项含概率、等级、状态和随访状态。
   - `CapturePointOut` 和巡检点位接口要带出上面所有新增字段；`FieldOut` 要带出 `facility_type`。
8. **前端**：
   - `types.ts` 和 `api/index.ts` 按资源各加一个对象。
   - 地块页每行加「株档案」入口，进入 `/fields/:id/units`（新 `UnitsView`）：表格，加批量建档对话框，设施类型可编辑，可筛选 `created_from=ingest`。
   - 单株时间线 `/units/:id`（新 `UnitTimelineView`）：每个日期一行，正面和叶背各一列缩略图；补拍图标出第几次；质量不合格的图灰显并标原因；
     同一行显示风险分和预测、随访状态。
   - 风格按 AGENTS 用户偏好：专业 SaaS 风，配色克制。
9. **模拟器**：`simulator/run.py` 加 `--v2` 选项。打开后给每个点填 `observation_key`（按垄号和点位推出 `R..-P..`）、`route_chainage_m`、`view`（side=upper），并给包填 `client_package_id`。
   不加选项时仍发 v1。rover 本计划不改（由 0016-B 负责），但 `rover.test_run_smoke` 必须继续通过。
10. **文档**：
    - ARCHITECTURE「契约」补上 v2 最小子集和幂等语义；重新生成 db-schema。
    - AGENTS 代码地图：表数加一，并登记新路由和新页面。
    - 技术债台账：新增「坐标不可为空」；rover 的 409 问题注明「平台侧已在 0014 解决，等 0016-B 接入」。

## 验收（测试必须覆盖）
- 现有 `test_ingest` 不改动、全部通过（v1 兼容）。
- 出现 v2 字段但 `schema_version` 不是 "2.0" 时返回 422。
- 幂等：同键同内容返回 200 + duplicate；同键异内容返回 409；无键时旧逻辑不变；唯一约束冲突路径（直接预插一条同键记录）。
- 株号：自动建档；推荐格式能解析出垄号和株序号；自定义键的垄号、株序号为空。批量建档幂等。
- 关联：
  - 有株号的点按株聚合；
  - 同一株跨两趟巡检能形成历史；
  - 邻株是同垄 ±1 株和相邻垄；网格键和株键不会互为邻居；
  - 只有网格数据时，risk-lr 的输出与改动前一致（回归测试）。
- 时间线：两天三张图（正面、叶背、叶背补拍）按日期聚合正确；viewer 可读；写操作对 viewer 返回 403。
- `GET /ingest/patrol-schema` 的导出里包含新字段；前端 `pnpm typecheck && pnpm build` 通过。

## 决策记录
- 已定（建档时）：见「设计」1–10。执行中新做的取舍逐条追加在这里。

## 进度
- [ ] 迁移 0015 + 模型 + 重新生成 db-schema
- [ ] 协议字段 + 校验 + 幂等 + 株号自动建档
- [ ] 风险输入按株关联（含 risk-lr 回归测试）
- [ ] 株档案接口与时间线接口
- [ ] 前端株档案页、时间线页
- [ ] simulator `--v2`
- [ ] 文档：ARCHITECTURE 契约、AGENTS 代码地图、技术债台账
