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

先确认电脑（后端）已启动，并知道它的局域网 IP（例如 `10.104.160.64`）。平台需要登录（决策 D15）：
请管理员分配一个操作员账号，通过环境变量提供（口令不要写在命令行里）。

```bash
export AGRISCOUT_USERNAME=rover AGRISCOUT_PASSWORD='<口令>'
```

```bash
# 无摄像头 / 在电脑上先测链路：合成图 + 假云台、假里程计，停车补拍并分步上传（默认模式）
.venv/bin/python run.py --api http://10.104.160.64:8000 --fake --layout layout.example.json --stops 5

# 真车：云台、补光、编码器驱动还没接，暂用旧模式——USB 摄像头拍 20 个点，间隔 3 秒
.venv/bin/python run.py --api http://10.104.160.64:8000 --mode legacy --device rover-001 --points 20 --interval 3 --spool-dir /var/lib/agriscout/spool

# 只补传上次断网或进程中断留下的巡检包
.venv/bin/python run.py --api http://10.104.160.64:8000 --flush-spool --spool-dir /var/lib/agriscout/spool
```

## 停车补拍模式（默认，计划 0016 阶段 A、B）

`--mode stops`（默认）：每个停车点按视角序列（默认 `views.example.json`：一张正面 + 两张叶背仰拍补光）逐个拍，
每张当场用 `iq-rule-v1` 判断清晰度、过曝、欠曝、逆光，不合格就补拍（叶背视角每次加 `--pitch-step` 度），
每次尝试都记成一个点上传。照片拍一张落盘一张（`<spool-dir>/<巡检目录>/`），断电不丢；
下次运行时中断的巡检自动组包排队，加 `--resume` 则从断点续拍。云台、补光、编码器驱动还没接，目前只能配合 `--fake` 使用。

```bash
# 假相机按脚本依次给出 normal/blurry/overexposed/dark/backlit，演示补拍
.venv/bin/python run.py --api http://10.104.160.64:8000 --fake --stops 5 --fake-script normal,blurry,blurry
```

**株号定位**（阶段 B）：`--layout` 给出棚内布局（`layout.example.json`，与平台批量建档同结构：每垄的垄号、株数、株距、第 1 株的行内位置），
`--row` 选本趟巡哪一垄（默认第一垄）。每个停车点按里程读数推算株号：株序号 = round((行内位置 − 起点) / 株距) + 1。
读到本垄的标签（二维码内容 = 株号）时以标签为准，并把「标签株的布局位置 − 当时的里程读数」记为偏差，校正后续株；
同一停车点的照片统一用标签结果。`position_source`：读到标签为 `tag`，按编码器推算为 `encoder`，假里程计为 `estimated`；
坐标沿垄按行内位置估算，不代表真实定位。不给布局时只认标签。给了布局时 `--stops`、`--stop-spacing` 默认取该垄株数和株距。

**分步上传**（阶段 B，协议 v2）：拍完后组成只含元数据的 v2 包放进队列（`client_package_id` = 队列包号），照片留在逐点目录里。
上传时先逐张按 SHA-256 查平台上有没有（`GET /api/v1/media/exists`），没有才传（`POST /api/v1/media`），再提交只含照片 URL 的包，
内存里一次只有一张照片。平台返回 200 + `duplicate`（同一个包已收过，比如上次回执丢了）按成功处理，删队列文件和照片目录；
返回 409（同包号内容不同）时标记 `needs_manual`，之后的补传跳过它，见下文「失败行为」。平台另对每张照片按同一公式算一遍质量，
写进分析结果的 `detail.image_quality`。

## 温湿度记录仪 CSV 上传（计划 0015）

棚内冠层温湿度记录仪通常只能导出 CSV。`env_upload.py` 按参数读列名、时区和编码，分批调用
`POST /api/v1/fields/{field_id}/env-readings`（每批最多 5000 条），用的账号和令牌参数与 `run.py` 相同：

```bash
.venv/bin/python env_upload.py --api http://<后端IP>:8000 --field-id 3 --csv th-01.csv --sensor-key th-01 \
  --time-col 时间 --temp-col 温度 --rh-col 湿度 --tz +08:00 --encoding gbk
```

- 时间不带时区时按 `--tz` 解释（默认东八区），自带时区的保持不变；格式特殊时用 `--time-format`（strptime 写法）。
- 湿度列允许带 `%`；叶面湿度列可选（`--wetness-col`，0–1）。
- 有解析不了的行时默认整份文件不上传，并打印行号；确认后加 `--skip-bad` 跳过坏行。
- 平台按「传感器 + 时刻」去重，同一个文件重复上传是安全的，已成功的批次重传时会被跳过。

## 无硬件烟测

安装 `requirements.txt` 后，可从仓库根目录运行最小闭环与失败路径检查：

```bash
python -m unittest rover.test_run_smoke rover.test_acquire rover.test_point_store rover.test_env_upload \
  rover.test_positioning rover.test_upload_v2
```

烟测使用本地 HTTP mock，不导入后端内部模块，也不需要摄像头；它覆盖 `--fake` 上传、巡检包时间顺序、非 JSON/网络错误，以及采集失败时的资源清理；
`test_upload_v2` 用按接口合同写的假平台检查 v2 包的字段约束、先传照片后交包、照片已有时跳过、重复补传与 409。

## 关键参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--api` | `http://localhost:8000` | 后端地址（真车填电脑局域网 IP） |
| `--device` | `rover-001` | 设备编号，须唯一，会幂等建档 |
| `--field-id` | 0 | 已有地块 id；0 表示自动建一块测试田 |
| `--points` | 10 | 采样点数量（legacy 模式） |
| `--interval` | 2.0 | 两次拍照间隔（秒），0=不等待 |
| `--step` | 0.5 | 相邻点间距（米），legacy 模式估算 `distance_m` 用 |
| `--camera` | 0 | USB 摄像头索引 |
| `--width` / `--height` | 640 / 480 | 上传照片分辨率（越小上传越快） |
| `--fake` | 关 | 不用摄像头，用合成图测链路 |
| `--crop` | `cucumber` | 自动建种植记录用的作物：`cucumber` 黄瓜（生育期为占位值，待农技复核）或 `wheat` 冬小麦 |
| `--spool-dir` | `.rover-spool` | 完整巡检包的本地持久队列目录，真车建议使用持久化绝对路径 |
| `--upload-retries` | 2 | 网络或 5xx/429 等临时错误的额外重试次数 |
| `--retry-delay` | 0.5 | 指数退避的基础等待秒数 |
| `--flush-spool` | 关 | 只补传队列，不启动新的采集 |
| `--mode` | `stops` | `stops` 停车按视角序列拍并补拍，分步上传 v2 包；`legacy` 沿直线等间隔拍一张，发 v1 包 |
| `--views` / `--stops` / `--stop-spacing` | 示例文件 / 5 / 0.4 | stops 模式的视角序列、停车点数、假里程计间距（米）；给了布局时后两项默认取该垄株数和株距 |
| `--layout` / `--row` | 空 / 第一垄 | 棚内布局 JSON 和本趟巡的垄号；给了布局才按里程推算株号 |
| `--max-attempts` / `--pitch-step` | 3 / 5 | 每个视角最多拍几次；叶背补拍每次加的仰角（度） |
| `--fake-script` | 空 | `--fake` 时假相机依次产出的图像类型，逗号分隔 |
| `--resume` | 关 | stops 模式从上次中断处续拍 |
| `--username` / `--password` | 环境变量 `AGRISCOUT_USERNAME` / `AGRISCOUT_PASSWORD` | 平台账号（操作员及以上）；首次访问受保护接口时自动登录，令牌过期自动重登 |
| `--token` | 环境变量 `AGRISCOUT_TOKEN` | 已签发的访问令牌，与账号口令二选一 |

## 当前边界（无传感器阶段）

- `distance_m`：legacy 模式按 `--step` 固定步长估算（匀速假设）；stops 模式取里程计读数（`--fake` 时为假里程计，`distance_source=configured`），**接编码器后改为真实里程**。
- `lng` / `lat`：从 `--base-lng/--base-lat` 沿正北走直线（stops 模式按校正后的行内位置），**接 GPS/RTK 后填真实坐标**；棚内跨日关联以株号为准。
- `weather`：留空 `null`，**接 DHT22 / BH1750 后填温湿光**。

这些字段替换时，协议（`POST /api/v1/ingest/patrol`）和前端都无需改动——这正是"平台业务不因数据源改变而修改"的设计目标（README 红线第 4 条）。

## 代码结构与失败行为

`run.py` 按职责拆分为 HTTP 客户端、照片采集源、本地队列、建档、点位采集和巡检包组装，
因此可以用 `--fake` 在没有摄像头时验证链路；相机、云台等实现在 `hardware.py`，可以单独替换 `CameraCapture` 接入其他相机。
每次完整采集会先以临时文件加原子替换写入本地队列，再尝试上传；上传成功后删除队列文件，网络错误或服务端临时错误会保留原始巡检包，后续可用 `--flush-spool` 补传。
重试不会重新拍照，也不会改变原始时间戳。legacy 模式下参数越界、非 JSON 响应或任一点拍摄失败都会终止当前任务，不上传不完整巡检包
（stops 模式下单张拍摄失败只记一个无照片的点，继续拍）；无论成功还是失败，HTTP 客户端和摄像头都会释放。

重复补传与冲突（阶段 B）：v2 包带稳定的 `client_package_id`，平台对同一个包的重传返回 200 + `duplicate`，rover 按成功删除队列。
HTTP 409（v2 包同包号内容不同，或 v1 包撞上同一地块、设备、开始时间）不重试，队列文件标记 `needs_manual: true` 并保留照片目录，
之后的 `--flush-spool` 跳过它、返回 1。核对平台上的巡检后，要重传就把该文件里的 `needs_manual` 改成 `false`，要放弃就删掉这个队列文件
（对应的照片目录会在下次启动时清掉）。

## 下一步接传感器

在 `run.py` 的 `capture_points.append(...)` 里，把对应字段补上真实值即可：

```python
"distance_m": encoder_distance,       # 编码器累计里程
"lng": gps_lng, "lat": gps_lat,       # GPS/RTK 坐标
"weather": {"temp_c": t, "humidity_pct": h, "light_lux": lux},  # 传感器快照
```
