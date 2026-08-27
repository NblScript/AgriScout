# 0002 · M-AI：YOLOv8n 麦穗检测识别管线

## 状态
**已完成** ✅——40 epochs 训练（P=0.92 / R=0.88 / mAP50=0.94），真实照片端到端检出 53/38 穗，
引擎切换验证通过。后续事项（真车照片重训、risk 生育期化、病害检测）转入 tech-debt-tracker。
最后更新：2026-08-27。

## 下载源弯路（网络环境记录，后续换源时省时间）

| 尝试 | 结果 |
|---|---|
| kagglehub 匿名（多个 GWD 镜像 slug） | 全部 403——Kaggle 匿名下载已不可用 |
| Zenodo / HuggingFace / global-wheat.com | 本网络完全不可达（TLS 建立失败） |
| git clone GitHub | 大流量 TLS 被 GFW 掐断（GnuTLS -110） |
| **codeload tarball 单流** | ✅ 653MB @ ~10MB/s |
| 兜底方案（未用） | api.github.com trees 拿全量清单 + raw/jsDelivr 逐文件（均实测 200） |

## 背景

- **为什么**：识别是项目最大软肋（当前 L0 占位=颜色统计）。真车照片 2026.10 才有，
  等照片再搞 YOLO 会死锁——先用公开数据集把「数据→训练→Analyzer 插拔」整条路跑通，
  真图到位后只换数据重训（识别线 L1，主计划 §8.1）。
- **数据集取舍**：
  - Global Wheat Head Detection（公开集）：俯视麦穗 bbox 单类检测，与 0.5m 俯拍形态一致，标签干净 ✅
  - 小麦病害公开集（PlantVillage 等）：多为实验室条件，噪声大，与田间照片域差过大 ❌（真图到位后自采补）
- **训练/运行时分离**：`ml/` 独立 venv（torch+CUDA 只进训练环境）；后端懒加载 ultralytics，
  `requirements-ml.txt` 可选依赖；默认 analyzer 仍 placeholder，既有测试零回归。
- **目标定位**：本里程碑 = 管线全通，不是精度 SOTA。

## 决策记录

| 决策 | 结论 |
|---|---|
| vigor 信号融合 | 麦穗密度分(0.6 权重，40 穗/图饱和) + 绿色覆盖率(0.4)，沿用占位版分档阈值 |
| NDVI/risk 公式 | 沿用占位版公式不变——保证跨引擎版本语义可比，规则引擎无感 |
| 胁迫检出语义 | YOLO 版保留枯黄色胁迫色检出（规则引擎 status 层依赖它，语义不回退） |
| 模型溯源 | `analyzer_version = "yolo-<模型文件名>"`；best.pt 导出 backend/models/（gitignore） |
| pip 大轮子 | /tmp 是 3.8G tmpfs，装 torch 必 Errno 28——`TMPDIR=~/.pip-tmp` 指主盘；默认 PyPI 33KB/s，阿里镜像 25 倍速 |
| 数据集下载 | kagglehub 匿名 403 → 改 GitHub 镜像 DhruvMakwana/Global-Wheat-Detection codeload tarball（labels 已是 YOLO 格式，免转换） |
| 后台任务 | 长任务必须用工具的 run_in_background 参数启动（shell 内 `&` 会随调用超时被连坐杀掉）；`| tail` 会缓冲输出——直接重定向到文件 |
| 推理输入 | ultralytics predict() 不收原始 bytes，`_detect` 先转 PIL（冒烟测试抓出，Analyzer 协议 bytes 契约不变） |

## 最终结果

- 训练：40 epochs / 0.58h（RTX 4060 8GB），验证集 **P=0.921 R=0.884 mAP50=0.940 mAP50-95=0.540**
- 导出：`backend/models/wheat-yolo-v1.pt`（6.2MB，gitignore 不入库）
- 端到端验证：`ANALYZER_BACKEND=yolo` 重启后端 → 模拟器 28 点全分析
  （analyzer_version=yolo-wheat-yolo-v1，合成照片 0 检出属预期）→
  **真实 GWD 照片走完整 ingest→分析 API：检出 53/38 穗**，vigor=5，人机数据全链路贯通
- 交付物：ml/ 训练三脚本、后端 YoloAnalyzer + settings 分派、`image_color_stats` 公共底座、
  test_yolo_analyzer.py 7 项（fake 注入免 torch）、README 训练章节

## 已知局限（转 tech-debt-tracker）

- 胁迫色公式不分生育期：成熟期黄田被误判 risk=1.0（真实照片验证暴露）——需按生育期条件化
- GWD→自采域差：合成/公开图与真车图存在域差，真车照片到位后重训
- 后端推理依赖完整 torch（~2GB）——小内存部署时导出 ONNX

## 下一步（超出本计划）

- 真车照片（2026.10）到位后重训，本计划协议零改动
- 病害检测训练需 bbox 标注回流支持（画框功能，见技术债）
