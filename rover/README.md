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
# 真车：USB 摄像头，拍 20 个点，间隔 3 秒；断网包保存在 .rover-spool
.venv/bin/python run.py --api http://10.104.160.64:8000 --device rover-001 --points 20 --interval 3 --spool-dir /var/lib/agriscout/spool

# 无摄像头 / 在电脑上先测链路：用合成图
.venv/bin/python run.py --api http://10.104.160.64:8000 --fake

# 只补传上次断网或进程中断留下的巡检包
.venv/bin/python run.py --api http://10.104.160.64:8000 --flush-spool --spool-dir /var/lib/agriscout/spool
```

## 无硬件烟测

安装 `requirements.txt` 后，可从仓库根目录运行最小闭环与失败路径检查：

```bash
python -m unittest rover.test_run_smoke
```

烟测使用本地 HTTP mock，不导入后端内部模块，也不需要摄像头；它覆盖 `--fake` 上传、巡检包时间顺序、非 JSON/网络错误，以及采集失败时的资源清理。

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
| `--spool-dir` | `.rover-spool` | 完整巡检包的本地持久队列目录，真车建议使用持久化绝对路径 |
| `--upload-retries` | 2 | 网络或 5xx/429 等临时错误的额外重试次数 |
| `--retry-delay` | 0.5 | 指数退避的基础等待秒数 |
| `--flush-spool` | 关 | 只补传队列，不启动新的采集 |

## 当前边界（无传感器阶段）

- `distance_m`：按 `--step` 固定步长估算（匀速假设），**接编码器后改为真实里程**。
- `lng` / `lat`：从 `--base-lng/--base-lat` 沿正北走直线，**接 GPS/RTK 后填真实坐标**。
- `weather`：留空 `null`，**接 DHT22 / BH1750 后填温湿光**。

这些字段替换时，协议（`POST /api/v1/ingest/patrol`）和前端都无需改动——这正是"平台业务不因数据源改变而修改"的设计目标（README 红线第 4 条）。

## 代码结构与失败行为

`run.py` 按职责拆分为 HTTP 客户端、照片采集源、本地队列、建档、点位采集和巡检包组装，
因此可以用 `--fake` 在没有摄像头时验证链路，也可以单独替换 `CameraCapture` 接入其他相机。
每次完整采集会先以临时文件加原子替换写入本地队列，再尝试上传；上传成功后删除队列文件，网络错误或服务端临时错误会保留原始巡检包，后续可用 `--flush-spool` 补传。
重试不会重新拍照，也不会改变原始时间戳。参数越界、非 JSON 响应或任一点拍摄失败都会终止当前任务，不上传不完整巡检包；无论成功还是失败，HTTP 客户端和摄像头都会释放。

当前后端尚未提供稳定的 client package id。HTTP 409 只会保留在本地队列并提示待核对，不能直接当作幂等成功删除，以免不同巡检包发生时间冲突时丢数据。

## 下一步接传感器

在 `run.py` 的 `capture_points.append(...)` 里，把对应字段补上真实值即可：

```python
"distance_m": encoder_distance,       # 编码器累计里程
"lng": gps_lng, "lat": gps_lat,       # GPS/RTK 坐标
"weather": {"temp_c": t, "humidity_pct": h, "light_lux": lux},  # 传感器快照
```
