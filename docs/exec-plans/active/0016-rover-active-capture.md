# 0016 · rover 主动采集：质量反馈补拍、逐点落盘、协议 v2、离线执行计划

## 状态
2026-10-03 建档；同日阶段 A 完成（M16 阶段 A，分支 `claude/project-thread-i8yjbh`）；2026-10-08 阶段 B 完成（M16 阶段 B），同日阶段 C 完成（M16 阶段 C）；B、C 的 PR 合并后归档。总览和共同约定见 [计划 0013](0013-greenhouse-active-acquisition.md)，开工前先读。
本计划分三个阶段，每个阶段单独一个 PR，里程碑都记作 M16（主题里注明阶段）；不涉及迁移。
- 阶段 A：第一批，没有依赖，可与 0014 并行。
- 阶段 B：依赖 0014 合并（已完成）。
- 阶段 C：依赖 0015 合并（已完成，计划文件已归档；计划口径见决策 D18）。

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
- 已定（阶段 A）：清晰度只统计卷积结果的内圈。Pillow 卷积原样保留最外一圈像素，纯色图会因边框测出虚假清晰度
  （320×240 全 3 灰度图测得 224）；两边同改。缩放「只缩不放」，长边 ≤320 的图保持原尺寸。
- 已定（阶段 A）：拍照抛异常算一次尝试，原角度重试（不加仰角），用满次数同样记 `max_attempts`；照片能拍到但解不开时照片照样落盘，质量记 `undecodable`。
- 已定（阶段 A）：标签在每个停车点读到第一个就停，之后的点沿用该株号；只读有照片的点。
- 已定（阶段 A）：中断的巡检默认在下次运行时按已拍的点直接组包排队；`--resume` 续拍最近一趟，参数（视角、停车点数、补拍上限）以建档时写进 `meta.json` 的为准。
  续拍从未完成的视角继续，尝试次数接着数。
- 已定（阶段 A）：非 `--fake` 的 stops 模式在建目录前就因云台驱动未接入而报错退出；试拍若要用真相机，需先接云台/补光驱动或另加手动模式。
- 已定（阶段 B）：`POST /media` 新建返回 201、已有返回 200，URL 相同；Content-Type 只认 image/jpeg、image/png（否则 415），
  扩展名按魔数定（与包内 base64 照片同一规则），同一份字节无论走哪条路都是同一个 URL，重传的元数据包内容才不变。超限 413，空体 422。
- 已定（阶段 B）：`/media/` 引用的存在性校验放在包号幂等和「地块 + 设备 + 开始时间」判重之后、落库之前：同一个包的重传先按重复处理。
  三个后端老用例拿不存在的 `/media/` 文件当「读不到的照片」，改用外部 URL，用例意图不变。
- 已定（阶段 B）：stops 模式不再把照片 base64 进队列包。组包写成 v2 元数据包（点里带本地 `photo_file`），照片留在逐点目录，
  目录写 `queued.json` 封存（不再续拍、不再重复组包）。每次上传都重新逐张查重，平台 URL 不落盘：省掉「平台丢了照片但车上记着 URL」的错配。
  成功后先删队列文件、再删照片目录；中间断电留下的「已封存但没有队列文件」的目录，下次启动时清掉。
- 已定（阶段 B）：409 不重试，队列文件标 `needs_manual`，补传时跳过、`--flush-spool` 返回 1；人工核对后改回 false 重传或删文件放弃。
  v1 包（legacy 模式）撞上「地块 + 设备 + 开始时间」的 409 也这样处理。
- 已定（阶段 B）：同一停车点拍的是同一株，组包时整个停车点统一取读到标签那一刻的株号和位置；读到标签之前的点在本地 JSONL 里仍记推算值。
  不合平台株号正则的标签内容不上传（否则整包 422），留在本地 `tags` 里。
- 已定（阶段 B）：`distance_m` 是里程读数，`route_chainage_m` 是加偏差后的行内位置；`distance_source` 假里程计记 configured、
  真编码器记 encoder。给了布局时 `--stops`、`--stop-spacing` 默认取该垄株数和株距，假里程计从该垄第 1 株的位置起步。
  续拍时偏差取断电前最后一个点记下的值。一次只巡一垄（`--row`），换垄留给阶段 C 按计划执行时处理。
- 已定（阶段 B）：`--crop cucumber` 的生育期（发芽 7 天、幼苗 30 天、初花 20 天、结果 63 天，共 120 天）和品种都是占位，待农技复核，WP6 定稿。
- 已定（阶段 B）：默认改为 stops 后，`test_run_smoke` 里两个验证旧模式的用例显式加 `--mode legacy`；`test_point_store` 的组包用例改按 v2 断言；
  `test_acquire` 的假客户端补上查重和上传两个方法。没有删除或跳过用例。
- 已定（阶段 C）：计划文件由 `--plan-fetch` 生成（格式 `agriscout-rover-plan/1`）：最近一次计划的四张名单合成一张停车清单，按垄、株序号排好；
  补拍株的视角取自 `GET /revisit-tasks?task_type=revisit` 里的 `parameters.views`（最近计划的返回里没有任务参数，不为此改接口），
  取不到或不合法时按标准视角拍并在下载时提示；任务已完成或作废的株不列入。下载时顺带登记设备，离线拍完的包上传时平台才认得它。
- 已定（阶段 C）：确认名单的株照常停车、按标准视角拍新照片供人看，但车不回报确认（label）任务：按 D18 这类是推给人确认的，
  前端待确认页按「未完成的确认任务」列株、人确认后关任务（D20），车关掉会让人看不到。计划写的「回报每条任务」只覆盖补拍、全覆盖、抽查。
- 已定（阶段 C）：任务结果在组包时按逐点记录算好、随包写进队列信封（`task_reports`），中断后自动组包的巡检也一样。判定：
  补拍要有一张合格的叶背图，全覆盖和抽查要有一张合格图；停车处核对出的株号不是计划株、布局里找不到、巡检中断都算没完成。
- 已定（阶段 C）：回报在包收下之后做：先 `PATCH {result_note}`（同时拿到平台上的当前状态），完成的再按状态机一步步走到 completed；
  没完成的只写原因、状态不动，留给下一版计划复用或作废，不用 cancelled（那是「放弃」）。平台上已结束（409）、已删除（404）、
  状态刚被改过（422）的任务跳过；网络错误让整包留在队列，下次重传按重复补传处理，回报接着做（写说明和走状态都可重复）。
- 已定（阶段 C）：按计划执行时车要「开到某株」，`hardware.py` 加底盘接口 `Drive.go_to(row_no, chainage_m)`，假底盘直接到位、
  假标签读车所在的那株，真实底盘同云台一样只留接口。每换一垄偏差从 0 起（假定底盘在垄头对齐里程计，真底盘接入时再定），
  续拍时取这一垄断电前最后记下的偏差；跨垄时经度按每垄 1 米示意错开。`--plan` 需要 `--layout`，不用 `--row/--stops/--stop-spacing`。
- 已定（阶段 C）：`--plan` 和 `--resume` 在拍完之前用不到平台，连不上时照常拍、包留在队列并返回 0；其余模式联网检查失败照旧报错。
  计划日期不是今天、或不在清晨叶背窗口内时只打印提示。`--plan` 遇到可续拍的非计划巡检时先续拍那一趟、提示下次再执行计划。
- 已定（阶段 C）：计划株在平台上是自定义键（布局里有垄号株号）时，推算或标签核对到这株就用平台上的键，不另建株档案。

## 进度
- [x] A1 硬件抽象与假实现
- [x] A2 `iq-rule-v1`（rover）
- [x] A3 视角序列与补拍
- [x] A4 逐点落盘
- [x] A5 `--mode stops`
- [x] A6 平台图像质量
- [x] A7 两边一致性测试
- [x] B1 照片上传接口与 ingest 校验
- [x] B2 v2 上传与幂等处理
- [x] B3 定位
- [x] B4 作物默认值、模式切换、README
- [x] C 离线执行计划与任务回报
