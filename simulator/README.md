# AgriScout 虚拟巡田模拟器

> 顶层独立工具：**只通过 HTTP 与平台对话，禁止 import 后端任何内部代码**。
> 它是"真车"的软件替身——能跑通它，就证明巡检包协议端到端成立（基线 D5）。

## 快速开始

```bash
# 前置：平台已启动（backend :8000），并有一个操作员账号（backend: python -m app.tools.create_user --username sim --role operator）
cd simulator
export AGRISCOUT_USERNAME=sim AGRISCOUT_PASSWORD='<口令>'   # 也可用 --username/--password 或 --token
python run.py --scenario healthy          # 或 dry / patchy_disease
```

运行环境：`httpx` + `pillow`（见 requirements.txt）。
可直接复用后端解释器：`../backend/.venv/bin/python run.py --scenario dry`。

## 三种场景

| 场景 | 注入的问题 | 预期规则命中 |
|------|-----------|--------------|
| `healthy` | 无 | 仅生育期常规建议（routine 层） |
| `dry` | 土壤墒情沿行程 68%→30% 线性走低 | `R-WHEAT-DROUGHT-JOINTING`（需生育期匹配）|
| `patchy_disease` | 巡程中段聚集性枯黄斑块（模拟病害空间聚集性） | `R-WHEAT-STRESS-PATCH` 等 status 层 |

## 可调参数

```bash
python run.py --scenario dry \
  --rows 8 --row-length 30 --step 0.5 \   # 地块规模与采样步长
  --sowing-days-ago 50 \                   # 播种于 N 天前 → 决定当前生育期(日历法)
  --device sim-001 --seed 42               # 设备编号 / 随机种子(可复现)
```

建档全部幂等：设备按 code、地块/作物按名称复用；种植记录按 (田,作物,播种日) 复用。

加 `--v2` 发协议 v2 最小子集（计划 0014）：行内点带株号 `R{垄}-P{株}`、`route_chainage_m` 和 `view`（正面），
包头带 `client_package_id`（重发同一包，平台返回 200 + `duplicate`），平台按株号自动建档。不加时仍发 v1。

## 它验证了什么

1. **协议契约**：上传严格走 `POST /api/v1/ingest/patrol`；
   Schema 单一事实源在平台侧导出：`GET /api/v1/ingest/patrol-schema`
2. **性能红线**：200+ 点 / 200+ 张照片的包秒级入库，识别绝不在上传请求里做
3. **异步管线**：`analysis_status` pending→running→done 进度可轮询
4. **建议闭环**：分析完成自动生成带出处的建议，阈值规则吃到的观测值会插值进文案

## 目录结构

```
simulator/
├── run.py         # CLI 编排入口
├── client.py      # 平台 HTTP 客户端 + 幂等建档助手
├── geo.py         # 米制局部坐标→经纬度；S形垄行路径；边界 GeoJSON
├── weather.py     # 日变化天气曲线 + 墒情衰减剖面
├── photo.py       # Pillow 合成农田照片（绿苗/枯斑/裸土）+ 黄瓜叶片近景（按病斑面积标定占位分析器分数）
├── scenarios.py   # 场景预设（问题注入策略）
├── epidemic.py    # 病害扩散元胞模型（潜伏期 + 天气 + 空间扩散）
├── season.py      # 多日期模拟季：上传、风险预测、模拟随访、导出真值
├── greenhouse.py  # 大棚黄瓜霜霉病模型（布局、小时温湿度、侵染与发展、可见性、人工确认），纯模型无 IO
├── greenhouse_run.py  # 大棚闭环：建档 → 环境 → 每天拉计划、拍照、确认 → 导出真值
├── test_greenhouse.py # 大棚模型单测（仓库根目录 python -m unittest simulator.test_greenhouse）
├── test_epidemic.py  # 病害模型单测（仓库根目录 python -m unittest simulator.test_epidemic）
└── test_geo_v2.py    # --v2 株号推导单测（仓库根目录 python -m unittest simulator.test_geo_v2）
```

## 多日期模拟季（执行计划 0008）

`season.py` 在同一块地上按固定间隔反复巡检，用来开发和检验「时序 + 空间」的风险预测与复巡、标注策略：

```bash
cd simulator
../backend/.venv/bin/python season.py --seed 7                 # 默认 36 天、每 3 天一趟、10 垄 × 30 m
../backend/.venv/bin/python season.py --days 45 --rows 16 --row-length 40 --seed 11   # 更大的田，发病事件更多
```

- **病害模型**（`epidemic.py`，只用标准库）：侵染后经潜伏期才可见；可见病斑按距离向周围传播；
  每天的传播强度由湿度、叶面湿润时长和温度决定（条锈病样参数，**未经农学校准，只检验方法流程**）。
- **照片**：严重度 ≥ 0.3 时基础巡检稳定拍得到病斑，更早只按比例偶尔拍到；另有 3% 的非病害黄褐色干扰。
- **随访**：固定 25% 参照区域每趟随访，另加 10% 随机抽查；10% 记为证据不足。窗口内首次显症记阳性，否则记阴性。
- **日期**：整季放在过去，预测窗口在运行时已全部结束（满足 D10 的阴性口径）。同一天重跑会复用已有巡检。
- **模型**：默认用平台启发式 `risk-heuristic-v2`；`--model-version risk-lr-v1` 改用训练好的风险模型（需先在后端运行 `app.tools.train_risk_lr`），
  同一种子的随访会抽到相同的区域和巡检，两个模型可以直接对比。
- **输出**：`simulator/out/season-truth-field<id>.json`（逐点逐日严重度、逐日气象站记录、巡检映射），
  交给 `backend/app/tools/replay_eval.py` 做 H1–H3 离线重放。

## 大棚黄瓜闭环与策略比较（计划 0017）

`greenhouse.py` 生成一份大棚「真值世界」，`greenhouse_run.py` 用它把 0014–0016 的闭环通过 HTTP 跑一遍：

```bash
cd simulator
../backend/.venv/bin/python greenhouse_run.py --days 10                        # 闭环：需操作员账号，每次新建一个模拟大棚
../backend/.venv/bin/python greenhouse_run.py --facility plastic_tunnel --rows 6 --plants 40 --seed 3
for s in $(seq 1 20); do ../backend/.venv/bin/python greenhouse_run.py --offline --days 30 --seed $s; done   # 只导出真值
cd ../backend && .venv/bin/python -m app.tools.greenhouse_replay --truth ../simulator/out/greenhouse-truth-*.json
```

- **模型**：日光温室或塑料大棚，`R{垄}-P{株}` 布局；逐小时温湿度（塑料大棚昼夜温差大、夜间更湿）；
  每个湿润且温度适宜的小时按「外源基数 + β × 明显期邻株数」侵染，之后潜伏 → 早期 → 明显；
  可见性按 视角 × 时段 × 状态 给出检出概率，另有拍摄不合格和补拍成功概率。**全部是设计假设，不是实测。**
- **闭环每天**：`POST /fields/{id}/patrol-plans` 拉计划 → 补拍名单只拍叶背、不合格重拍，全覆盖和抽查拍正面和叶背 →
  发 v2 包（`view.accepted` 写拍摄当场的质量结论）→ 等分析 → 拍照任务走完状态机 →
  确认名单按真值写三阶段标注（人工误判率 `--human-error`）并关确认任务（与前端 D20 同一做法）。
- **照片**：合成叶片图的病斑面积按占位分析器标定，叶背合格图的风险分约为：明显期 0.85、早期 0.55、健康株误检 0.5、看不出 0.1。
- **日期**：闭环的模拟季放在过去（第 0 天 = 今天 − days），只上报到季末的环境；`--offline` 默认第 0 天固定为 2026-03-02，
  同一种子导出的真值逐字节一致。
- **已知差异**：标注时间是平台写入的真实时间，晚于所有模拟照片，计划把这些照片都当成人已看过，
  所以闭环里被人确认过的株不会再推给人（D22 的重新推送也不会触发）；离线比较按模拟时间记标注，不受影响。
- **输出**：`simulator/out/greenhouse-truth-<seed>.json`（`agriscout.greenhouse-truth.v1`：逐小时环境、每株侵染/早期/明显时刻、
  每天状态码、可见性与分数参数、闭环记录），交给后端 `app.tools.greenhouse_replay` 比较巡检策略。
  报告开头写明「模拟结论只证明流程」：病害规律是按设计放进来的，数字不能当作效果证据（D5）。
