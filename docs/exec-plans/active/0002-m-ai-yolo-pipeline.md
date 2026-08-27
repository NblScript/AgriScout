# 0002 · M-AI：YOLOv8n 麦穗检测识别管线

## 状态
**进行中**——后端 YoloAnalyzer 已完成并通过测试；ml 依赖安装曾因 /tmp(tmpfs 3.8G) 磁盘满失败两次，
已改用 `TMPDIR=~/.pip-tmp` + 阿里镜像重装；数据下载与训练待依赖装完后执行。
最后更新：2026-08-27。

## 背景

- **为什么**：识别是项目最大软肋（当前 L0 占位=颜色统计）。真车照片 2026.10 才有，
  等照片再搞 YOLO 会死锁——先用公开数据集把「数据→训练→Analyzer 插拔」整条路跑通，
  真图到位后只换数据重训（识别线 L1，主计划 §8.1）。
- **数据集取舍**：
  - Global Wheat Head Detection（Kaggle 公开集）：俯视麦穗 bbox 单类检测，与 0.5m 俯拍形态一致，标签干净 ✅
  - 小麦病害公开集（PlantVillage 等）：多为实验室条件，噪声大，与田间照片域差过大 ❌（真图到位后自采补）
- **训练/运行时分离**：`ml/` 独立 venv（torch+CUDA 只进训练环境）；后端懒加载 ultralytics，
  `requirements-ml.txt` 可选依赖；默认 analyzer 仍 placeholder，38 项测试零回归。
- **目标定位**：本里程碑 = 管线全通，不是精度 SOTA；GPU 为 RTX 4060 Laptop 8GB，全量可训。

## 决策记录

| 决策 | 结论 |
|---|---|
| vigor 信号融合 | 麦穗密度分(0.6 权重，40 穗/图饱和) + 绿色覆盖率(0.4)，沿用占位版分档阈值 |
| NDVI/risk 公式 | 沿用占位版公式不变——保证跨引擎版本语义可比，规则引擎无感 |
| 胁迫检出语义 | YOLO 版保留枯黄色胁迫色检出（规则引擎 status 层依赖它，语义不回退） |
| 模型溯源 | `analyzer_version = "yolo-<模型文件名>"`；best.pt 导出 backend/models/（gitignore） |
| pip 源 | 默认 PyPI 在本机仅 33KB/s，改阿里镜像（25 倍速）；/tmp 是 3.8G tmpfs，大轮子必须 TMPDIR 指主盘 |
| 数据集下载 | kagglehub 免登录拉公开集；CSV[xmin,ymin,w,h] → YOLO 归一化 txt，90/10 切分，seed=42 |

## 进度

- [x] 环境检查：RTX 4060 8GB + 32 核 + 931G 磁盘可用
- [x] `ml/` 独立 venv + requirements（ultralytics/kagglehub，阿里镜像）
- [x] `ml/data/prepare_gwd.py` 数据准备脚本（下载+YOLO 格式转换+切分+data.yaml）
- [x] `ml/train.py`（GPU 自适应 batch，yolov8n 预训练起步）
- [x] `ml/export_model.py`（best.pt → backend/models/wheat-yolo-v{N}.pt，版本自动递增）
- [x] 后端 `YoloAnalyzer`（懒加载、build_result 与推理解耦可测）+ settings `ANALYZER_BACKEND/YOLO_MODEL_PATH` 分派
- [x] base.py 抽取 `image_color_stats` 公共底座，占位版同步重构复用
- [x] `tests/test_yolo_analyzer.py` 7 项（fake 模型注入，无需 torch）——38 全绿零回归
- [x] README 训练章节、gitignore ML 产物
- [ ] ml 依赖重装完成（进行中，等后台任务）
- [ ] GWD 数据集下载转换（依赖装好后跑 prepare_gwd.py）
- [ ] 后台训练 train.py（约 40 epochs，预计 <1h GPU）
- [ ] 导出模型 + backend venv 装 requirements-ml.txt
- [ ] 切 `ANALYZER_BACKEND=yolo` 起服务，模拟器 dry 场景验证 analyzer_version 切换与 ear_count 字段
  （注：模拟器合成照片可能 0 检出，属预期——验证点是管线打通而非检出率）
- [ ] commit（`M-AI:` 前缀）

## 下一步（接手从这里开始）

1. 检查 ml 依赖安装：`ls ml/.venv/lib/python3.14/site-packages | wc -l`（>10 即成功）
2. `cd ml && .venv/bin/python data/prepare_gwd.py`（约 2GB 下载）
3. `cd ml && .venv/bin/python train.py` 后台跑
4. 按上方「进度」清单继续
