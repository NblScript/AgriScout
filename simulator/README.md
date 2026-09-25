# AgriScout 虚拟巡田模拟器

> 顶层独立工具：**只通过 HTTP 与平台对话，禁止 import 后端任何内部代码**。
> 它是"真车"的软件替身——能跑通它，就证明巡检包协议端到端成立（基线 D5）。

## 快速开始

```bash
# 前置：平台已启动（backend :8000）
cd simulator
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
├── photo.py       # Pillow 合成农田照片（绿苗/枯斑/裸土）
├── scenarios.py   # 场景预设（问题注入策略）
├── epidemic.py    # 病害扩散元胞模型（潜伏期 + 天气 + 空间扩散）
├── season.py      # 多日期模拟季：上传、风险预测、模拟随访、导出真值
└── test_epidemic.py  # 病害模型单测（仓库根目录 python -m unittest simulator.test_epidemic）
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
