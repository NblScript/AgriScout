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
└── scenarios.py   # 场景预设（问题注入策略）
```
