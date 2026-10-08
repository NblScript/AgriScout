# AGENTS.md — AgriScout 代理地图

巡知（AgriScout）：面向病害风险预测与主动学习的农田智能巡检系统。小车沿垄近地拍照 → 平台异步逐点分析 →
区域风险预测 → 复巡/标注任务 → 人工随访与复核 → 数据集冻结与模型闸门；规则引擎给出可溯源农事建议。
2027 挑战杯科技发明 A 类。2026-10 起方向调整为设施大棚黄瓜霜霉病的风险驱动闭环主动采集（D16，以计划 0013 为准，
docs/09 申报书待重写）。已完成：平台软件闭环、离线重放（H1–H3）、risk-lr-v1、rust-cls-v1、登录与角色权限（D15）、前端按大棚工作流重做（D19、D20）、大棚模拟与策略离线比较（D21）、rover 主动采集与离线执行计划（D23）；
进行中：计划 0013（温室方向总览，接子计划前先读其「共同约定」）、0007（与作物无关的剩余项）。

**本文件是地图不是说明书**——约束看红线节，细节按「文档导航」按需读。
所有跨会话知识必须落在仓库文件里，聊天记录等于不存在。

## 命令速查

```bash
# 后端（8000）：venv 用 --without-pip 创建（Python 3.14 无 ensurepip），包装 --target 装依赖
cd backend && .venv/bin/python -m alembic upgrade head
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000
cd backend && .venv/bin/python -m pytest            # 提交前必须全绿
cd backend && .venv/bin/python -m app.tools.sync_rules      # 规则 YAML → 规则表
cd backend && .venv/bin/python -m app.tools.gen_db_schema   # 改表后重生成 db-schema.md
cd backend && .venv/bin/python -m app.tools.create_user --username admin --role admin  # 建首个管理员（无默认账号）

# 前端（5173，/api 代理后端）
cd frontend && pnpm dev                              # 需 export XDG_CACHE/HOME/STATE（见 README）
cd frontend && pnpm typecheck && pnpm build

# 模拟器（一键闭环：建档→采样→上传→分析→建议）；需 AGRISCOUT_USERNAME/PASSWORD（操作员账号）
cd simulator && ../backend/.venv/bin/python run.py --scenario dry   # healthy/dry/patchy_disease；加 --v2 发协议 v2 子集（株号/视角/幂等键）
cd simulator && ../backend/.venv/bin/python season.py --seed 7      # 多日期病害扩散模拟季（导出真值）
cd backend && .venv/bin/python -m app.tools.replay_eval --truth ../simulator/out/season-truth-field1.json  # H1–H3 离线重放
cd backend && .venv/bin/python -m app.tools.train_risk_lr --truth ../simulator/out/season-truth-field1.json  # 训练 risk-lr-v1
cd simulator && ../backend/.venv/bin/python greenhouse_run.py --days 10   # 大棚黄瓜闭环（计划 0017）；加 --offline --days 30 --seed N 只导真值
cd backend && .venv/bin/python -m app.tools.greenhouse_replay --truth ../simulator/out/greenhouse-truth-*.json  # 巡检策略离线比较（只证明流程）
python -m unittest simulator.test_epidemic simulator.test_geo_v2 simulator.test_greenhouse  # 仓库根目录运行，病害模型、株号推导、大棚模型单测

# 真车采集端（树莓派 + USB 摄像头；--fake 无摄像头测链路）
cd rover && .venv/bin/python run.py --api http://<后端IP>:8000 --fake
cd rover && .venv/bin/python run.py --api http://<后端IP>:8000 --fake --layout layout.example.json --fake-script normal,blurry  # 默认停车补拍 + 株号定位 + 分步上传（0016-A/B；真车暂用 --mode legacy）
cd rover && .venv/bin/python run.py --api http://<后端IP>:8000 --plan-fetch plan.json --field-id 3  # 下载巡检计划；进棚 --plan plan.json --layout <布局> --fake 离线执行（0016-C）
cd rover && .venv/bin/python env_upload.py --api http://<后端IP>:8000 --field-id 3 --csv th-01.csv --sensor-key th-01  # 温湿度记录仪 CSV（0015）
python -m unittest rover.test_run_smoke rover.test_acquire rover.test_point_store rover.test_env_upload rover.test_positioning rover.test_upload_v2 rover.test_plan  # 仓库根目录运行，无硬件

# ML 训练（独立环境）
cd ml && .venv/bin/python data/prepare_gwd.py && .venv/bin/python train.py
cd ml && .venv/bin/python export_model.py            # 产物 → backend/models/（gitignore）
cd ml && .venv/bin/python data/prepare_nwrd.py && .venv/bin/python train_rust.py && .venv/bin/python eval_rust.py
cd ml && .venv/bin/python export_model.py --kind rust  # 条锈病模型 → rust-cls-v{N}.pt + .json 说明（后端 DISEASE_MODEL_PATH）
python -m unittest ml.test_prepare_nwrd            # 仓库根目录运行，NWRD 切块口径单测
cd ml && .venv/bin/python al_features_nwrd.py && cd ../backend && .venv/bin/python -m app.tools.al_replay_images \
  --samples ../ml/data/nwrd_cls/al_features.json --pool-prevalence 0.05   # H3 真实数据选样对比（计划 0011）
```

## 代码地图

| 路径 | 职责 |
|---|---|
| `backend/app/models/` | 24 张表，每实体一文件；`timestamps.py` 公共 mixin；`__init__.py` 为注册中心 |
| `backend/app/api/v1/` | 路由层：CRUD + ingest + 分析 + 建议 + 标注 + stats + 报告 + Agent + 规则修订 + `device_protocol`（注册/心跳/事件/故障注入）+ `software_loop`（风险/复巡/随访/数据集/模型评估）+ `auth`/`users`（登录与用户管理，D15）+ `observation_units`（株档案/批量建档/单株时间线，计划 0014）+ `greenhouse`（棚内环境上报与查询、每株状态、巡检计划，计划 0015）+ `media`（照片分步上传与查重，计划 0016-B） |
| `backend/app/services/analysis/` | Analyzer 协议（base.py）+ 占位颜色版 + YOLO 版（麦穗，可选）+ disease_classifier（条锈病图块分类，可选）+ image_quality（iq-rule-v1，每点写 detail）+ 后台 runner |
| `backend/app/services/` | advice(规则引擎) / agent_chat+agent_tools(L2 诊断) / agent_rule_draft+rule_feedback+shadow_run+rule_revision(L1 起草生效) / llm_report(报告) / ingest+observation_units(重传幂等、株号解析与自动建档) / storage / risk_prediction+risk_inputs+region_association+active_learning+evidence_feedback+dataset_governance(M7 研究闭环，纯函数优先) / evaluation_metrics+offline_replay(随访指标与 H1–H3 离线重放) / logistic+risk_features+risk_model(risk-lr 可训练风险模型，D12) / revisit_planning(线上复巡生成，与离线共用联合策略，D17) / greenhouse_env+plant_state+patrol_planner+greenhouse_plans(大棚环境指标、每株状态、planner-v1 与计划落库，D18/D22) / greenhouse_replay(大棚巡检策略离线比较，调用线上 planner，D21) |
| `backend/app/tools/` | `sync_rules`（YAML 同步）、`gen_db_schema`（表结构快照）、`replay_eval`（离线重放报告）、`train_risk_lr`（训练导出风险模型）、`al_replay_images`（H3 真实图像数据选样对比）、`greenhouse_replay`（大棚巡检策略比较报告）、`create_user`（建号/重置口令） |
| `backend/rules/wheat.yaml` | 规则种子库 18 条（单一事实源，经 sync_rules 同步入表） |
| `backend/app/schemas/` | DTO + 巡检包协议 v1 + 设备协议（对采集端的合同） |
| `backend/migrations/versions/` | 手写 Alembic 迁移，`00NN_主题` 命名（当前 0016） |
| `frontend/src/views/` | HomeView（/home 工作台）+ ConfirmQueueView（待确认，侧滑确认）+ FieldDetailView 与 `field/` 五个标签页（概览/巡检计划/株档案/环境/巡检记录；旧 `/fields/:id/units`、`/plan` 即其子路由）+ UnitTimelineView（单株时间线）+ PatrolsView/PatrolDetailView（回放外壳，大棚按株 / 大田地图两种模式，D19）+ ResearchLoopView + 七个管理页（地块/作物/种植/设备/用户/规则修订审批/系统状态）+ BigScreenView（/screen 展示屏）+ LoginView |
| `frontend/src/layouts/` · `styles/` | 外壳（计划 0018）：AppShell + 分组侧栏 + 顶栏（面包屑、地块切换器、展示屏、用户菜单），导航定义在 `nav.ts`；`styles/tokens.css` 设计令牌是颜色、间距、字号的唯一来源（株状态色、任务类型色在此），`theme.css` 把 Element Plus 变量映射到令牌 |
| `frontend/src/components/` | `ui/` 通用组件（PageHeader/SectionCard/StatCard/StateTag/TaskTypeTag/QualityBadge/EmptyState）+ PlantGrid（「垄 × 株」状态网格）+ EnvPanel/ConfirmPanel（工作台、大棚详情、展示屏共用）+ `plant/`（单株照片、状态、确认表单，D20）+ `patrol/`（回放各块：播放条、照片与病斑框、单株卡、采样点卡、问一问/报告/建议分区）+ MapCanvas、EChart；`composables/` 放共用数据加载（useGreenhouseBoard、useFieldDetail、useTimelineCache） |
| `frontend/src/api/index.ts` · `types.ts` | 每资源一个 api 对象；类型单一事实源，对齐 backend schemas |
| `simulator/` | 独立虚拟巡田，只走 HTTP（禁止 import 后端内部）；`season.py` 多日期病害扩散模拟季；`greenhouse.py` + `greenhouse_run.py` 大棚黄瓜模型与闭环（D21） |
| `rover/` | 真车采集端：`run.py` 编排上传与 spool 断网续传；`hardware`（硬件接口+假实现）/`quality`（iq-rule-v1）/`acquire`（视角补拍）/`point_store`（逐点落盘）/`positioning`（布局与株号定位）/`upload`（照片分步上传）/`plan`（按巡检计划离线执行与任务回报）/`env_upload`（温湿度 CSV 上传）；只走 HTTP |
| `ml/` | YOLO 训练环境（与后端运行时分离）：麦穗检测（GWD）、条锈病图块分类（NWRD，D14） |
| `tools/` | download_tiles.py 离线瓦片下载（高德源） |

## 不可变红线（违反=返工）

1. **异步分析**：上传请求绝不同步识别照片（2600 张包会超时）——分析走 BackgroundTasks + analysis_status 轮询（D2）
2. **规则单一事实源**：规则改 YAML → sync 入表；Advice 冻结 rule_snapshot，永不回写；审批通过的修订案须回写 YAML，否则 sync 报 conflicts 并跳过（`--force` 以 YAML 覆盖）
3. **照片不进库**：SHA-256 内容寻址存 `media/`，库内只存 URL（D6）；内容寻址意味着同一文件可能被多个巡检共享，删除前必须确认无引用
4. **协议即合同**：巡检包/设备协议 schema 变更必须同步 `/api/v1/ingest/patrol-schema` 导出、模拟器与 rover
5. **认证**：全路由挂 `get_current_user`（令牌校验 + 公开白名单 + 角色策略集中在 `core/deps.py`），不得绕过；新增公开接口须改白名单并过 `test_auth` 全接口匿名 401 检查（D15）
6. **采集端隔离**：simulator 与 rover 只走 HTTP，禁止 import 后端内部代码（D5）
7. **产物不入库**：`*.db`、`*.pt`、`backend/models/`、`media/`、`ml/data|runs|.venv`、`.pytest-tmp-*`、`.rover-spool/` 均 gitignore
8. **测试红线**：backend pytest 全绿才能 commit；协议/引擎改动必须带新测试
9. **Agent 权限边界**：L2 诊断 Agent 只读；规则修订 Agent 只能起草，必须影子运行 + 人工审批才生效
10. **证据闸门**：随访终态不可改；模型评估只能绑定已冻结数据集的 test split 才能审批发布

## 工作约定

- **里程碑 = commit 单元**，中文消息 `M{n}: 主题——交付物`；文档变更单独 `docs:` 前缀 commit
- **执行计划先行**：非常规改动先在 `docs/exec-plans/active/` 建计划（模板见其 README），完成后结论
  并入注册表/README、计划文件删除；决策（编号 D/B/T/L）登记 `docs/design-docs/decision-registry.md`
- **机械校验**：`backend/tests/test_docs.py` 守护文档新鲜度（链接/行数≤120/db-schema 快照），
  改表结构后运行 `python -m app.tools.gen_db_schema` 重新生成
- **测试临时目录**：pytest 用 `--basetemp` 时放到系统临时目录，不要在仓库根目录堆 `.pytest-tmp-*`
- **时间约定（D9）**：时间列一律用 `UTCDateTime`（库内存 UTC、读回带时区）；按天计的农事语义用 `core/timeutil.field_date`
- **设备安全锁存**：维护态只能人工解除或清除「唯一原因」的注入故障，规则集中在 `services/device_safety.py`
- **用户偏好**：全中文交流与文档；表格化、克制配色（前端走专业 SaaS 风不走炫酷大屏）

## 文档导航（按需读）

| 何时 | 读 |
|---|---|
| 改数据库 / 看表结构 | `docs/generated/db-schema.md`（生成物，勿手改） |
| 动 Analyzer 或接入新识别模型 | `ARCHITECTURE.md`「契约」「能力分级」、`services/analysis/base.py`、决策 D14 |
| 动规则/建议逻辑 | `backend/rules/wheat.yaml` 文件头（格式）、`services/advice.py`、注册表「规则引擎生命周期」 |
| 动风险预测/复巡/数据集闸门 | 决策 D10–D13、D17，`api/v1/software_loop.py`、`services/revisit_planning.py`、`services/offline_replay.py` |
| 动大棚环境 / 每株状态 / 巡检计划 | 决策 D18、D22、`services/patrol_planner.py`、`services/greenhouse_plans.py`；改完用 `greenhouse_replay` 复跑策略比较（D21） |
| 动前端页面 / 颜色与样式 / 人工确认 | 决策 D19、D20，`styles/tokens.css`、`layouts/nav.ts`、`api/index.ts` 的 `confirmApi` |
| 查某个编号决策（D/B/T/L） | `docs/design-docs/decision-registry.md` |
| 动认证 / 角色 / 公开接口 | 决策 D15、`core/deps.py`、`core/security.py`、`tests/test_auth.py` |
| 理解整体架构 | `ARCHITECTURE.md`（本仓库） |
| 看当前在做什么 / 接手未完工作 | `docs/exec-plans/active/`（空则看 README「下一阶段」） |
| 已知问题 / 技术债 | `docs/exec-plans/tech-debt-tracker.md` |
| 比赛规则 / 参赛定位 / 合规 | `docs/design-docs/competition-rules.md`（大挑科技发明制作 A 类，带条款号） |
| 立项背景 / 比赛叙事 | 决策 D16 与计划 0013（当前方向）、docs/09（申报书，小麦版待重写）、docs/08（系统方案）、docs/01（调研） |
| 硬件 / 小车对接 | `rover/README.md`、决策 D23（rover 采集、上传与按计划执行的口径）、docs/08 §5–§7（硬件分工、Pi 端软件、TX2 推理）、注册表 T 系列 |
| 查已删除的旧文档（已完成计划、审查记录、主计划等） | `docs/exec-plans/README.md`「已删除的历史文档」 |
