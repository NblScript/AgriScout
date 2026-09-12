# AgriScout 真车采集端（树莓派 + USB 摄像头）

> 与 `simulator/` 同权：**只通过 HTTP 巡检包协议与平台对话，绝不 import 后端内部代码**。
> 它是真车的软件入口——拍照、攒采样点、打包上传到平台，前端地图回放。

## 环境要求

- 树莓派（或任何能跑 Python 的 Linux/Windows 机器）
- USB 摄像头（Robot-Eye 等 UVC 摄像头）
- Python 3.10+

## 安装依赖

```bash
cd rover
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

> 树莓派上若 `opencv-python-headless` 装不上（老 32 位系统），可改用系统包：
> `sudo apt install -y python3-opencv`，并把 `run.py` 里 `import cv2` 对应版本跑通即可。

## 运行

先确认电脑（后端）已启动，并知道它的局域网 IP（例如 `10.104.160.64`）。

```bash
# 真车：USB 摄像头，拍 20 个点，间隔 3 秒
.venv/bin/python run.py --api http://10.104.160.64:8000 --device rover-001 --points 20 --interval 3

# 无摄像头 / 在电脑上先测链路：用合成图
.venv/bin/python run.py --api http://10.104.160.64:8000 --fake
```

## 关键参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--api` | `http://localhost:8000` | 后端地址（真车填电脑局域网 IP） |
| `--device` | `rover-001` | 设备编号，须唯一，会幂等建档 |
| `--field-id` | 0 | 已有地块 id；0 表示自动建一块测试田 |
| `--points` | 10 | 采样点数量 |
| `--interval` | 2.0 | 两次拍照间隔（秒），0=不等待 |
| `--step` | 0.5 | 相邻点间距（米），估算 `distance_m` 用 |
| `--camera` | 0 | USB 摄像头索引 |
| `--width` / `--height` | 640 / 480 | 上传照片分辨率（越小上传越快） |
| `--fake` | 关 | 不用摄像头，用合成图测链路 |

## 当前边界（无传感器阶段）

- `distance_m`：按 `--step` 固定步长估算（匀速假设），**接编码器后改为真实里程**。
- `lng` / `lat`：从 `--base-lng/--base-lat` 沿正北走直线，**接 GPS/RTK 后填真实坐标**。
- `weather`：留空 `null`，**接 DHT22 / BH1750 后填温湿光**。

这些字段替换时，协议（`POST /api/v1/ingest/patrol`）和前端都无需改动——这正是"平台业务不因数据源改变而修改"的设计目标（README 红线第 4 条）。

## 下一步接传感器

在 `run.py` 的 `capture_points.append(...)` 里，把对应字段补上真实值即可：

```python
"distance_m": encoder_distance,       # 编码器累计里程
"lng": gps_lng, "lat": gps_lat,       # GPS/RTK 坐标
"weather": {"temp_c": t, "humidity_pct": h, "light_lux": lux},  # 传感器快照
```
