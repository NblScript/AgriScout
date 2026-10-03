# AgriScout 巡知

AgriScout（巡知）是一套面向病害风险预测与主动学习的农田智能巡检系统。
巡检小车沿垄行近地拍照，平台异步完成逐点分析，把同一观察区域的多日期观测串起来预测病害风险，
再据此安排复巡和专家标注；每条预警、建议和人工结论都可以追溯到原图、模型版本和规则快照。

一句话概括：**用有限的巡检和人工投入，获得更有助于判断病害风险的证据，并通过可验证的反馈持续改进。**

> 项目面向 2027 年第二十届“挑战杯”全国大学生课外学术科技作品竞赛（大挑）科技发明制作 A 类。
> 规则要点、参赛定位与合规清单见 [competition-rules](docs/design-docs/competition-rules.md)。
> **2026-10 方向调整**：目标场景由小麦大田改为设施大棚（日光温室、塑料大棚）黄瓜霜霉病，做风险驱动的闭环主动采集
> （决策 D16，[计划 0013](docs/exec-plans/active/0013-greenhouse-active-acquisition.md)）。下文的小麦规则、模型与模拟季保留为方法验证；
> [docs/09 申报书](docs/09-project-application.md) 是小麦版，待按新方向重写；硬件与部署以 [docs/08 系统方案](docs/08-system-solution.md) 为准。

## 为什么做

小地块病害管理的难点不在“拍更多照片”，而在四件事（申报书第二节）：

- 观察不足：知道地块有风险，却难以确定先检查哪里；
- 判断不足：一次识别说明不了未来会怎样变化；
- 学习成本高：大量相似照片不等于有效标注，专家时间有限；
- 反馈不足：预警发出后，是否被证实难以追踪，误报漏报原因说不清。

项目据此研究三项相互关联的创新：以区域连续观察为基础的多源时空风险预测；主动复巡与主动学习联动的预算分配；
贯穿预警、复核和学习的证据反馈。系统输出具体区域的风险等级、预测时间窗、依据和复查任务，由农技人员确认关键结论。
采样间距、视角和复访间隔通过试验确定（0.5 米只是候选间距）。

## 核心闭环

```text
地块/作物/设备建档
        ↓
巡检小车或模拟器上传巡检包
        ↓
照片内容寻址存储 + 采样点/天气入库
        ↓
后台逐点分析（生育期、长势、病害候选）
        ↓
规则引擎生成带快照的农事建议 → 地图回放、时间轴复盘、人工采纳/驳回
        ↓
按观察区域串联历史 → 风险预测（时间窗 + 依据）
        ↓
复巡 / 专家标注任务 → 人工随访结论
        ↓
数据集冻结 → 模型评估闸门 → 受控更新识别与风险模型
```

系统不把识别结果当成不可质疑的结论：每条建议都保留命中的规则版本，
每个分析结果都记录分析器版本，人工复核可以修正机器判断。

## 当前能力

- 基础管理：地块、作物、种植批次、设备的 CRUD。
- 登录与权限：账号登录（令牌有效期默认 12 小时）；管理员 / 操作员 / 只读三种角色，只读账号不能修改任何数据；管理员在「用户管理」页建号、改角色、停用、重置口令。
- 巡检接入：巡检包 v1 与 v2 最小子集（株号、行内位置、视角元数据），客户端包 ID 重传幂等（同包返回 200，不再 409），照片 SHA-256 内容寻址存储、分页和地理范围查询。
- 株档案：按株建档（批量生成 `R{垄}-P{株}`），上传时按株号自动关联、找不到就建档待核对；风险预测按株分区；单株时间线按日期并列正面和叶背照片、补拍次数、质量、复核与预测。
- 异步分析：上传快速返回，后台逐点执行；支持颜色统计占位分析器、可选 YOLO 麦穗分析器，以及可选条锈病识别模型（NWRD 公开田间数据训练，输出病斑图块位置与风险分）。
- 规则建议：天气阈值、分析状态、生育期保底三层规则；每点最多保留 Top-3；建议冻结 `rule_snapshot`。
- 可视化回放：Leaflet 地图、轨迹、采样点长势着色、时间轴、照片/天气/分析详情。
- 人工复核：建议采纳/驳回、采样点标签、标注修改和 NDJSON 训练集导出。
- AI 报告与问答：LLM 只作为解释层；诊断 Agent 只读查询，所有问答留痕。
- 规则进化：Agent 可以起草规则修订案，但必须经过影子运行和人工审批才能生效。
- 研究闭环：按逐点分析生成带时间窗和证据的风险预测，主动排序复巡/标注任务，记录人工随访结论，并以冻结数据集和模型评估闸门管理发布。
- 设备协议：设备幂等注册、心跳、设备/任务事件、可回放故障注入，以及设备领取复巡任务（`/devices/{id}/tasks/next`）。
- 虚拟巡田：独立模拟器提供 `healthy`、`dry`、`patchy_disease` 三种可复现场景；`season.py` 模拟整季多日期巡检，病害按潜伏期、天气和空间扩散发展，并模拟农技员随访。
- 实验评估：风险预测按观察区域串联历史巡检；`GET /risk-predictions/metrics` 从随访结果计算 PR-AUC、Brier、固定误报负担下的召回率和提前量；`replay_eval` 离线重放 H1 特征消融、H2 复巡策略、H3 标注选样。H3 另在 NWRD 真实图块上验证（`al_replay_images`）：候选池阳性比例抽稀到 ≤10% 时，平台联合选样达到随机选样 200 个标注的效果只需 100–120 个；NWRD 原始比例（约 1/3 阳性）下三种策略没有差别。抽稀条件是看到原始结果后追加的对照，结论需在试验田数据上复验。
- 可训练风险模型：`train_risk_lr` 用逻辑回归训练 `risk-lr-v1`（本区域图像、历史、邻近区域 5 个特征），生成预测时指定 `model_version=risk-lr-v1` 使用；训练与线上共用同一特征实现。
- 真车采集端：`rover/` 支持 USB 摄像头或合成图采集、本地 spool 断网续传、临时错误指数退避重试。

## 当前状态

软件线 M0-M6 已完成，识别和建议线也已打通：

| 方向 | 状态 | 说明 |
|---|---|---|
| 管理、接入、分析、建议、可视化 | 已完成 | 可用模拟器跑通完整闭环 |
| 标注回流 | 已完成 | 支持人工标签和 NDJSON 导出 |
| YOLO 识别管线 | 已完成 | 公开小麦数据集训练，默认仍使用零依赖占位引擎 |
| 条锈病识别模型 | 已完成 | `rust-cls-v1`：NWRD 公开田间数据训练，官方测试集图块 F1 0.82、ROC-AUC 0.93；默认不启用 |
| LLM 报告 | 已完成 | 未配置模型时静默关闭，不阻塞主链路 |
| 诊断 Agent / 规则修订 Agent | 已完成 | 分别遵守“只读”和“起草-审批”边界 |
| M7 软件闭环 | 已完成 | 风险、复巡、随访、数据集/模型闸门和设备任务接口已接入 |
| 登录与角色权限 | 已完成 | 全部接口需登录（健康检查与登录除外），三种角色，测试逐个接口核对匿名访问被拒（D15） |
| 真车采集端软件 | 已完成 | `rover/` 可用 `--fake` 无硬件跑通上传，烟测覆盖上传、断网续传与登录 |
| M7 真车接入 | 下一阶段 | 编码器/GPS/天气传感器尚未接入；目标是平台业务代码不因数据源改变而修改 |

需要明确的是：当前模型效果主要由公开数据和模拟数据验证，真实车载照片、农技阈值复核和田间对比实验仍是下一阶段的核心工作。

## 系统架构

```text
┌────────────── 采集端 ──────────────┐
│ 巡检小车(rover/) / 模拟器          │
│ RGB 照片 + 天气 + 坐标 + 里程       │
└───────────────┬────────────────────┘
                │ HTTP 巡检包协议 v1
                ▼
┌────────────── 平台后端 ─────────────┐
│ FastAPI API                         │
│ 接入 → 存储 → 异步分析 → 规则建议     │
│ 标注回流 / 报告 / Agent / 统计        │
└───────────────┬────────────────────┘
                │
       SQLite（开发）/ PostgreSQL（生产）
                │
┌────────────── 管理前端 ─────────────┐
│ Vue 3 + TypeScript                  │
│ Element Plus + Leaflet + ECharts     │
└─────────────────────────────────────┘
```

后端依赖方向是 `api → services → models/schemas → core`。采集端只依赖 HTTP 协议，
不 import 后端内部代码；识别器通过 `Analyzer` 协议替换，存储通过 `Storage` 协议替换。

## 仓库结构

| 目录 | 作用 |
|---|---|
| `backend/` | FastAPI 服务、SQLAlchemy 模型、Alembic 迁移、分析和规则引擎 |
| `frontend/` | Vue 管理台、巡检回放页、数据总览和规则审批页 |
| `simulator/` | 只走 HTTP 的独立虚拟巡田模拟器 |
| `rover/` | 真车采集端（树莓派 + USB 摄像头），只走 HTTP，带断网队列 |
| `ml/` | 独立的 YOLO 数据准备、训练和模型导出环境 |
| `docs/` | 申报书与系统方案、设计决策、执行计划、技术债、数据库结构快照 |
| `tools/` | 离线地图瓦片等辅助工具 |

## 快速运行

### 1. 启动后端

需要 Python 3.12+；当前开发环境使用 Python 3.14，开发数据库默认是 SQLite。

```bash
cd backend
python3 -m venv --without-pip .venv
SITE_PACKAGES=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
python3 -m pip install --target "$SITE_PACKAGES" -r requirements.txt
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.tools.sync_rules
# 平台没有默认账号：先建一个管理员（交互输入口令），再建一个给模拟器/小车用的操作员
.venv/bin/python -m app.tools.create_user --username admin --role admin --name 管理员
.venv/bin/python -m app.tools.create_user --username sim --role operator --name 模拟器
.venv/bin/python -m uvicorn app.main:app --port 8000
```

非开发环境（`ENVIRONMENT` 不是 `dev`）必须在 `backend/.env` 设置 `AUTH_SECRET`（令牌签名密钥），否则拒绝启动。

启动后可访问接口文档：<http://localhost:8000/docs>

### 2. 启动前端

需要 Node.js 和 pnpm。前端开发服务器默认使用 5173 端口，并将 `/api`、`/media` 代理到后端。

```bash
cd frontend
export XDG_CACHE_HOME=$PWD/../.pnpm-cache XDG_DATA_HOME=$PWD/../.pnpm-data XDG_STATE_HOME=$PWD/../.pnpm-state
pnpm install
pnpm dev
```

访问 <http://localhost:5173> 用上一步建的账号登录；独立数据总览页面为 <http://localhost:5173/screen>。

### 3. 跑一趟虚拟巡田

保持后端运行，另开终端执行（模拟器会建地块、传巡检包，需要操作员及以上账号）：

```bash
cd simulator
export AGRISCOUT_USERNAME=sim AGRISCOUT_PASSWORD='<上面设置的口令>'
../backend/.venv/bin/python run.py --scenario dry
```

可选场景：

```bash
../backend/.venv/bin/python run.py --scenario healthy
../backend/.venv/bin/python run.py --scenario patchy_disease
```

模拟器会自动建档、生成 S 形垄行采样、合成照片和天气、上传巡检包、轮询分析状态，并打印建议摘要。
加 `--v2` 改发协议 v2 子集：每个行内点带株号，平台自动建株档案，可在地块页「株档案」里看单株时间线。
### 4. 真车采集端（可选）

没有摄像头时可先用合成图验证链路，详细参数见 [rover/README.md](rover/README.md)：

```bash
cd rover
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
export AGRISCOUT_USERNAME=<操作员账号> AGRISCOUT_PASSWORD='<口令>'   # 或 --token
.venv/bin/python run.py --api http://<后端局域网IP>:8000 --fake
```

采集端对接合同由后端导出：

```text
GET http://localhost:8000/api/v1/ingest/patrol-schema
```

## 常用验证

```bash
# 后端测试
(cd backend && .venv/bin/python -m pytest)

# 前端类型检查与生产构建
(cd frontend && pnpm typecheck && pnpm build)

# 真车采集端无硬件烟测、病害模型单测（仓库根目录）
python -m unittest rover.test_run_smoke simulator.test_epidemic simulator.test_geo_v2

# 规则 YAML 同步到运行时规则表
(cd backend && .venv/bin/python -m app.tools.sync_rules)
```

后端健康检查：

```bash
curl http://localhost:8000/api/v1/health
```

## 识别与规则

默认分析器是 `placeholder-color-v0`，使用图像颜色统计估计绿色覆盖率、长势和胁迫风险，
适合零依赖演示，不等同于真实 NDVI。

如果已经训练并导出 YOLO 模型，可以在 `backend/.env` 中切换（两个模型可单独或同时启用，留空即不启用）：

```dotenv
ANALYZER_BACKEND=yolo
YOLO_MODEL_PATH=./models/wheat-yolo-v1.pt      # 麦穗检测：数穗估长势
DISEASE_MODEL_PATH=./models/rust-cls-v1.pt     # 条锈病识别：病斑图块与逐点风险分
```

后端推理需要 `pip install -r requirements-ml.txt`。条锈病模型的数据来源、测试指标与局限见
`backend/models/rust-cls-v1.json` 和决策 D14（[决策注册表](docs/design-docs/decision-registry.md)）。

训练环境与后端分离：

```bash
cd ml
python3 -m venv --without-pip .venv
SITE_PACKAGES=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
python3 -m pip install --target "$SITE_PACKAGES" -r requirements.txt
.venv/bin/python data/prepare_gwd.py
.venv/bin/python train.py --epochs 40
.venv/bin/python export_model.py
# 条锈病识别（NWRD，约 609 MB，自动校验 MD5；CPU 约 1 小时，GPU 几分钟）
.venv/bin/python data/prepare_nwrd.py
.venv/bin/python train_rust.py
.venv/bin/python eval_rust.py
.venv/bin/python export_model.py --kind rust
```

规则的单一事实源是 [backend/rules/wheat.yaml](backend/rules/wheat.yaml)。修改 YAML 后同步入表；历史建议使用冻结快照，不会被新规则回写。

## 设计红线

这些约束是项目的一部分，不是可选实现细节：

1. 上传请求只负责落库，识别必须异步执行，避免大巡检包超时。
2. 照片不进入数据库，数据库只保存内容寻址后的 URL。
3. 规则从 YAML 同步到数据库，建议必须冻结命中时的规则版本和条件。
4. 模拟器和真车采集端（`rover/`）都只走 HTTP 协议，不能绕过 HTTP 直接调用后端内部代码。
5. 所有接口统一经过 `get_current_user` 认证，公开白名单只有健康检查与登录，角色规则集中在一处（D15）。
6. L2 Agent 只读；规则 Agent 没有直接生效权，必须经过影子运行和人工审批。
7. 模型、数据库、照片和训练产物不进入 Git。

## 下一阶段

下一阶段是 **温室方向软件线**（执行计划见 [0013](docs/exec-plans/active/0013-greenhouse-active-acquisition.md)，
与作物无关的剩余改造见 [0007](docs/exec-plans/active/0007-application-alignment.md)）。场地核实与试拍前只做不依赖场地的部分：

- 棚内冠层温湿度接入、霜霉病环境风险指标，风险驱动的巡检计划（补拍、人工确认、随机抽查、低频全覆盖）（0015）；
- rover 按预设角度拍摄 + 逐张质量判断 + 补拍，逐点落盘与分步上传，离线执行计划，图像质量进入分析结果（0016）；
- 大棚黄瓜模拟场景，端到端跑通闭环，并离线比较固定巡检与风险驱动两种策略（0017）；
- 试拍拿到真实照片后：霜霉病识别基线、黄瓜规则草稿（待农技复核）；
- 时钟同步、盲法复核、数据集分组划分、TX2 部署验证（计划 0007）。

## 已知边界

- 默认颜色统计是占位算法，绿色覆盖率代理值不能当作真实 NDVI。
- YOLO 公开数据集与真实车载照片存在域差，真车数据到位后需要重训和重新评估。
- 条锈病模型只覆盖单一病害，训练数据为巴基斯坦田间近距离叶片图；输出是候选检出，须人工复核，车载照片到位后需微调并重新评估。
- 照片目录 `/media` 不做登录校验（浏览器图片请求无法携带令牌，照片 URL 为内容哈希）；复核人、审批人署名目前由前端提交并默认填当前用户。
- 登录暂无失败次数限制，部署到公网前需加限流或放在网关之后。
- 标注目前以整图标签为主，病害检测所需的框标注仍在技术债中。
- 离线地图瓦片只覆盖演示区域，更换演示田需要重新下载瓦片。
- 平台已支持客户端包 ID 幂等，但 rover 要到计划 0016 阶段 B 才发 v2 包；在此之前重复上传仍按“地块 + 设备 + 开始时间”判重，rover 收到 409 时保留本地队列等待人工核对。
- 小车目前用固定步长估算里程、沿直线估算坐标、天气字段为空，需接编码器、GPS/RTK 和温湿光传感器后替换。

## 文档入口

- [AGENTS.md](AGENTS.md)：代码地图、不可变红线和协作约定。
- [ARCHITECTURE.md](ARCHITECTURE.md)：分层架构、数据流、契约与能力分级。
- [docs/design-docs/competition-rules.md](docs/design-docs/competition-rules.md)：大挑规则要点、参赛定位与合规清单。
- [docs/09-project-application.md](docs/09-project-application.md)：申报书底稿（项目叙事以此为准）。
- [docs/08-system-solution.md](docs/08-system-solution.md)：目标系统方案（硬件分工、协议 v2、部署）。
- [docs/01-reference-research.md](docs/01-reference-research.md)：同类案例与论文调研。
- [rover/README.md](rover/README.md)：真车采集端安装、参数与失败行为。
- [docs/design-docs/decision-registry.md](docs/design-docs/decision-registry.md)：编号决策注册表与规则引擎生命周期。
- [docs/exec-plans/active/0013-greenhouse-active-acquisition.md](docs/exec-plans/active/0013-greenhouse-active-acquisition.md)：温室方向软件线总览（拆分、依赖顺序、共同约定）；子计划 0014–0017 在同一目录。
- [docs/exec-plans/active/0007-application-alignment.md](docs/exec-plans/active/0007-application-alignment.md)：进行中的执行计划（与作物无关的剩余改造：时钟、盲法复核、数据集划分、TX2）。
- [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md)：技术债台账（含历次审查未修项）。
- [docs/exec-plans/README.md](docs/exec-plans/README.md)：执行计划约定；已删除历史文档的取回方式。
- [docs/generated/db-schema.md](docs/generated/db-schema.md)：自动生成的数据库结构快照。

## 许可与使用

项目当前主要用于课程/竞赛原型和研究验证。部署到真实生产环境前，需要补充登录限流与操作审计、对象存储、断点续传、
监控告警、数据合规和农艺验证等能力。
