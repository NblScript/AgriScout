# AGENTS.md — AgriScout 代理地图

农田巡检平台：巡检小车每 0.5m 拍照+采天气 → 平台异步逐点分析（生育期/长势/穗数）→
规则引擎产出可溯源农事建议 → 人工复核标注回流训练集 → 风险预测/复巡/数据集与模型闸门。
2027 大挑比赛项目（科技发明 A 类）。当前阶段：软件线 M0–M6 与 M7 软件闭环已完成，下一步是 M7 真车接入。

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
cd simulator && ../backend/.venv/bin/python run.py --scenario dry   # healthy/dry/patchy_disease
cd simulator && ../backend/.venv/bin/python season.py --seed 7      # 多日期病害扩散模拟季（导出真值）
cd backend && .venv/bin/python -m app.tools.replay_eval --truth ../simulator/out/season-truth-field1.json  # H1–H3 离线重放
cd backend && .venv/bin/python -m app.tools.train_risk_lr --truth ../simulator/out/season-truth-field1.json  # 训练 risk-lr-v1
python -m unittest simulator.test_epidemic         # 仓库根目录运行，病害模型单测

# 真车采集端（树莓派 + USB 摄像头；--fake 无摄像头测链路）
cd rover && .venv/bin/python run.py --api http://<后端IP>:8000 --fake
python -m unittest rover.test_run_smoke             # 仓库根目录运行，无硬件烟测

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
| `backend/app/models/` | 23 张表，每实体一文件；`timestamps.py` 公共 mixin；`__init__.py` 为注册中心 |
| `backend/app/api/v1/` | 路由层：CRUD + ingest + 分析 + 建议 + 标注 + stats + 报告 + Agent + 规则修订 + `device_protocol`（注册/心跳/事件/故障注入）+ `software_loop`（风险/复巡/随访/数据集/模型评估）+ `auth`/`users`（登录与用户管理，D15） |
| `backend/app/services/analysis/` | Analyzer 协议（base.py）+ 占位颜色版 + YOLO 版（麦穗，可选）+ disease_classifier（条锈病图块分类，可选）+ 后台 runner |
| `backend/app/services/` | advice(规则引擎) / agent_chat+agent_tools(L2 诊断) / agent_rule_draft+rule_feedback+shadow_run+rule_revision(L1 起草生效) / llm_report(报告) / ingest / storage / risk_prediction+risk_inputs+region_association+active_learning+evidence_feedback+dataset_governance(M7 研究闭环，纯函数优先) / evaluation_metrics+offline_replay(随访指标与 H1–H3 离线重放) / logistic+risk_features+risk_model(risk-lr 可训练风险模型，D12) |
| `backend/app/tools/` | `sync_rules`（YAML 同步）、`gen_db_schema`（表结构快照）、`replay_eval`（离线重放报告）、`train_risk_lr`（训练导出风险模型）、`al_replay_images`（H3 真实图像数据选样对比）、`create_user`（建号/重置口令） |
| `backend/rules/wheat.yaml` | 规则种子库 18 条（单一事实源，经 sync_rules 同步入表） |
| `backend/app/schemas/` | DTO + 巡检包协议 v1 + 设备协议（对采集端的合同） |
| `backend/migrations/versions/` | 手写 Alembic 迁移，`00NN_主题` 命名（当前 0014） |
| `frontend/src/views/` | 七个管理页（系统状态/地块/作物/种植/设备/规则修订审批/研究闭环）+ PatrolsView/PatrolDetailView（回放/复核/问一问/报告）+ BigScreenView（/screen 总览）+ LoginView/UsersView（登录、用户管理） |
| `frontend/src/components/` | MapCanvas（Leaflet 封装，theme=light/dark）、EChart、ScreenPanel |
| `frontend/src/api/index.ts` · `types.ts` | 每资源一个 api 对象；类型单一事实源，对齐 backend schemas |
| `simulator/` | 独立虚拟巡田，只走 HTTP（禁止 import 后端内部）；`season.py` 多日期病害扩散模拟季 |
| `rover/` | 真车采集端：拍照→攒点→打包上传，本地 spool 断网续传；只走 HTTP |
| `ml/` | YOLO 训练环境（与后端运行时分离）：麦穗检测（GWD）、条锈病图块分类（NWRD，计划 0010） |
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
- **执行计划先行**：非常规改动先在 `docs/exec-plans/active/` 建计划（模板见其 README），
  完成移 `completed/`；决策（编号 D/B/T）登记 `docs/design-docs/decision-registry.md`
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
| 动 Analyzer 或接入新识别模型 | 主计划 §7.2（协议契约）、`services/analysis/base.py` |
| 动规则/建议逻辑 | 主计划 §7.3（YAML 格式）、`services/advice.py`、docs/05 规则生命周期节 |
| 动风险预测/复巡/数据集闸门 | `docs/exec-plans/completed/0005-software-completion.md`、`api/v1/software_loop.py` |
| 查某个编号决策（D/B/T/L） | `docs/design-docs/decision-registry.md` |
| 理解整体架构 | `ARCHITECTURE.md`（本仓库） |
| 看当前在做什么 / 接手未完工作 | `docs/exec-plans/active/`（空则看 README「下一阶段」） |
| 已知问题 / 技术债 | `docs/exec-plans/tech-debt-tracker.md`、`docs/reviews/`（代码审查记录、申报书方案评审） |
| 立项背景 / 比赛叙事 | docs/01（调研）、docs/07（介绍）、docs/08（系统方案）、docs/09（申报书） |
| 硬件 / 小车对接 | `rover/README.md`、docs/04 §9（硬件路线）、docs/06（嵌入式路线） |
