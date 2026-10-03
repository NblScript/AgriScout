# 0016 · rover 主动采集：质量反馈补拍、逐点落盘、协议 v2、离线执行计划

## 状态
2026-10-03 建档，未开工。总览和共同约定见 [计划 0013](0013-greenhouse-active-acquisition.md)，开工前先读。
本计划分三个阶段，每个阶段单独一个 PR，里程碑都记作 M16（主题里注明阶段）；不涉及迁移。
- 阶段 A：第一批，没有依赖，可与 0014 并行。
- 阶段 B：依赖 [0014](0014-plant-identity-protocol-v2.md) 合并。
- 阶段 C：依赖 [0015](0015-env-risk-patrol-planner.md) 合并。

## 背景
本计划对应创新点一：停车后在低位按预设仰角拍叶背，逐张判断质量，不合格就补拍。代码现状：
- `rover/run.py` 是一个 640 行的单文件，坐标按固定步长推成一条直线。
- 整趟的照片以 base64 形式放在内存里，采完才整包写入队列（`PackageSpool`）。2600 个点约 0.1–0.4 GB，而 Pi 3B 只有 1 GB 内存。
- 任何一个点拍照失败，整趟中止。
- 没有云台、补光、定位接口；作物写死为冬小麦（`WHEAT_STAGES`、`ensure_records`）。
- 依赖：httpx、opencv-python-headless、pillow。
- 平台从不测图像质量（技术债台账「复巡任务理由失真」）。
- 计划 0007 的 P0-3（逐点落盘）和 P1-6（图像质量）并入本计划。

## 范围
- 做：硬件抽象和假实现；`iq-rule-v1` 质量判断（rover 和后端各一份）；按视角序列拍摄并补拍；逐点落盘；
  照片分步上传；发送 v2 字段并处理幂等；离线执行巡检计划。
- 不做：真实云台、补光、编码器驱动（硬件没定型，只留接口，真实实现抛出明确的 NotImplementedError）；
  「叶背是否露出」的模型判断（等 WP5）；TX2 推理。

## 阶段 A：本地闭环 + 平台图像质量（第一批）
1. **`rover/hardware.py`**：
   - 定义五个 Protocol：`Camera.capture() -> bytes`、`Gimbal.move(pitch_deg, yaw_deg)`、`Light.set(on)`、`Odometer.distance_m()`、`TagReader.read(image) -> list[str]`。
   - 假实现：
     - `FakeCamera`：从 `run.py` 迁出 `FakeCapture`，可以按脚本依次产出正常、模糊、过曝、过暗、逆光图；
     - `FakeGimbal`：记录每次调用；
     - `FakeLight`、`FakeOdometer`：每次调用按步长前进；
     - `FakeTagReader`：每 N 次返回一次配置好的株号。
   - 真实实现：`CameraCapture` 从 `run.py` 迁入；`QrTagReader` 用 `cv2.QRCodeDetector`。
2. **`rover/quality.py` 中的 `iq-rule-v1`**（只用 Pillow，后端照同一公式实现）：
   - 预处理：`ImageOps.exif_transpose` 后转灰度，长边按 BILINEAR 缩到 320。
   - 各项指标：
     - `mean_luma`：灰度均值 / 255；
     - `clip_high`：灰度 ≥250 的像素占比；`clip_low`：灰度 ≤5 的像素占比；
     - `sharpness`：先用 `ImageFilter.Kernel((3,3), [0,1,0,1,-4,1,0,1,0], scale=1, offset=128)` 卷积，再取 `ImageStat` 方差；
     - `backlit`：上三分之一的均值减去中央九宫格的均值 ≥60，且中央均值 <70（0–255 尺度）。
   - 判定：sharpness≥40、clip_high≤0.05、clip_low≤0.20、且没有逆光时，`ok=true`；否则 `reasons` 列出 blurry / overexposed / underexposed / backlit。
   - 阈值放在 `QualityThresholds` dataclass 里，标「待试拍校准」。
3. **`rover/acquire.py`**：
   - 视角序列从 JSON 读入（附示例 `rover/views.example.json`：一张正面，再加两张叶背，仰角 35° 和 50°，叶背补光）。
   - `shoot_stop(...)` 对每个视角最多拍 `max_attempts` 次（默认 3）：叶背视角每次重拍把仰角加 `pitch_step_deg`（默认 5°）。
   - **每次尝试都记成一个点**：view 里写 attempt、accepted、quality。
   - 用满次数仍不合格时，最后一次记 `reshoot_reason="max_attempts"`，然后继续下一个视角。
   - 拍照抛异常时，记一个没有照片的点（`photo=None`，quality.reasons 写异常摘要），然后继续。
4. **`rover/point_store.py`（逐点落盘）**：
   - 每趟巡检一个目录 `<spool>/<patrol_uid>/`：
     - 照片 `photos/<seq>.jpg` 先写临时文件，fsync 后 rename；
     - 照片落盘之后，再往 `points.jsonl` 追加一行，并 flush + fsync；
     - `meta.json` 保存包头。
   - `PointStore.resume()` 从断点继续，并忽略末尾写了一半的行。
   - `build_package()` 逐张读取照片；阶段 A 仍组成 base64 的 v1 包，交给现有的 `PackageSpool` 和上传流程。
5. **`run.py` 加 `--mode stops`**：配合参数 `--views`、`--stops`、`--stop-spacing`、`--max-attempts`。
   默认仍是旧模式，阶段 B 再切换默认值。株号、行内位置、视角先只写进本地 JSONL，阶段 B 才上传。
6. **平台图像质量**：
   - 新建 `backend/app/services/analysis/image_quality.py`，实现同一套 `iq-rule-v1`；
   - `runner.py` 对每个分析的点都写入 `detail["image_quality"]`，与使用哪个分析器无关；
   - `analyzer_version` 不改，用 `method` 字段追溯。
7. **两边结果一致**：rover 和后端的测试在代码里用同一方法生成五张合成图：
   - 320×240 的棋盘格（8 px，灰度 60 和 200）；
   - 棋盘格再加 GaussianBlur(4)；
   - 全 255 中间放一块 128；
   - 全 3；
   - 上三分之一 250、其余 40。

   两边断言同一组期望值，容差为 sharpness 相对 1%，其余 1e-3。

验收 A：
- 假相机连续给出模糊图时，会触发补拍，到上限后记下原因并继续。
- 过曝和逆光图会被识别出来。
- 拍照异常不会中止整趟。
- 写到第 k 个点时模拟中断，重启后能恢复 k 个点，末尾的半行被忽略。
- 两边的一致性测试通过；后端分析结果里有 `image_quality`。
- `rover.test_run_smoke` 不改动、全部通过；新增测试为 `rover/test_acquire.py`、`rover/test_point_store.py`、`backend/tests/test_image_quality.py`。

## 阶段 B：协议 v2 + 分步上传（0014 合并后）
1. **后端照片接口**：
   - `POST /api/v1/media`：请求体是原始图片字节，Content-Type 为 image/jpeg 或 image/png，≤8 MB；返回 `{url, sha256, created}`。
   - `GET /api/v1/media/exists?sha256=`：返回 `{exists, url}`。复用 `services/storage.py` 的内容寻址。
   - ingest 校验：以 `/media/` 开头的 photo URL 必须在存储里真实存在，否则返回 422；外部 http URL 不校验。
   - 权限：operator 可用，viewer 自动 403。
   - 上传了但没被任何点引用的照片暂不清理，记一条技术债。
2. **rover 上传**：
   - 包标为 `schema_version: "2.0"`，`client_package_id` 用 `PackageSpool.package_id`（这个 ID 已经稳定）。
   - 每个点带上 observation_key、route_chainage_m、distance_source、position_source、view。
   - 上传顺序：先逐张查重并上传照片，再提交只含 URL 的元数据包；这样内存占用与点数无关。
   - 结果处理：返回 200 且 `duplicate=true` 时视为成功，删除队列；返回 409 时保留，并标记为待人工处理。
3. **`rover/positioning.py`**：
   - 布局从 JSON 读入（示例 `rover/layout.example.json`：`rows: [{row_no, plants, spacing_m, start_chainage_m}]`，与 0014 批量建档同结构）。
   - 行内位置取里程计读数；株序号 = round((chainage − start) / spacing) + 1。
   - 读到标签时以标签为准，记下偏差，并用来校正后续株。
   - `position_source` 取值：本点读到标签为 tag，按里程推算为 encoder，用假里程为 estimated。
   - 坐标沿垄估算，并声明 estimated（0013 已定）。
4. **其他**：
   - `ensure_records` 加 `--crop cucumber|wheat`，默认 cucumber。黄瓜生育期表先放占位值，标「待农技复核」，WP6 再定。
   - 默认模式切换为 `stops`，旧模式保留为 `--mode legacy`。
   - rover/README 更新。

验收 B：
- 生成的包满足 v2 字段约束；后端测试另用一份同结构的手写 v2 示例包。
- 重复补传返回 duplicate 后，队列被删除；返回 409 时保留。
- 照片已存在时跳过上传。
- 引用不存在的 `/media/` URL 返回 422。
- 标签校正株号的测试通过。

## 阶段 C：离线执行巡检计划（0015 合并后）
1. 在有网处运行 `--plan-fetch`：调用 `GET /fields/{id}/patrol-plans/latest`，保存为本地 `plan.json`。进棚后用 `--plan plan.json` 离线执行。
2. 执行规则：
   - 只在计划名单里的株停车；
   - 全覆盖、抽查、确认这三类株按标准视角序列拍；
   - 补拍株按任务 `parameters.views` 拍；
   - 计划给了清晨窗口而当前时间不在窗口内时，只提示，不阻止执行。
3. 回到有网处上传后，用现有的任务状态接口（`report_task_status`）回报每条任务的完成情况或失败原因。

验收 C：
- 用假硬件执行一份构造的计划：只拍了名单里的株，补拍株用了指定视角，任务状态回报正确。
- 断网时计划可以执行完，包留在队列里。

## 决策记录
- 已定（建档时）：见各阶段的设计。补拍的每次尝试都上传（0013 已定）。
- 已定（建档时）：质量公式两边各实现一份，由测试锁住一致性。
- 执行中的取舍逐条追加在这里。

## 进度
- [ ] A1 硬件抽象与假实现
- [ ] A2 `iq-rule-v1`（rover）
- [ ] A3 视角序列与补拍
- [ ] A4 逐点落盘
- [ ] A5 `--mode stops`
- [ ] A6 平台图像质量
- [ ] A7 两边一致性测试
- [ ] B1 照片上传接口与 ingest 校验
- [ ] B2 v2 上传与幂等处理
- [ ] B3 定位
- [ ] B4 作物默认值、模式切换、README
- [ ] C 离线执行计划与任务回报
