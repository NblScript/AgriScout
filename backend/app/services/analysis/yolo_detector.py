"""L1 识别：YOLOv8n 麦穗检测 + 颜色统计混合分析（主计划 §8.1 级别 L1）。

检测信号：单类 wheat_head bbox → 穗数密度估长势（0.5m 高密度采样的核心优势）；
颜色信号：复用 base.py 的 HSV 统计，绿色比率→NDVI 代理、胁迫色→风险分。
日历法生育期与颜色胁迫检出保持与占位版一致的语义，规则引擎零改动。

模型由 ml/train.py 训练产出（Global Wheat Head 公开集），真车照片到位后
换数据重训，本模块协议不变。ultralytics 为可选依赖：仅 backend=yolo 时加载。

病害（计划 0010）：配置 DISEASE_MODEL_PATH 后叠加条锈病图块分类（disease_classifier.py），
输出 stripe_rust 汇总检出，逐点风险分改由模型给出；颜色胁迫检出保留为独立类型，只作非病害胁迫提示。
麦穗模型可不配（YOLO_MODEL_PATH 为空）：长势/NDVI 代理/胁迫检出沿用颜色版，两个模型可单独或同时启用。
"""
import logging
from pathlib import Path
from typing import Any

from app.services.analysis.base import (
    AnalysisResult,
    Analyzer,
    CaptureContext,
    calendar_growth_stage,
    image_color_stats,
)
from app.services.analysis.disease_classifier import RustTileClassifier, TileProb, summarize_tiles
from app.services.analysis.placeholder_color import PlaceholderColorAnalyzer

logger = logging.getLogger(__name__)

# GWD 图均穗数约 44；以此为饱和密度基准换算密度分（粗标定，真车数据后修正）
TARGET_EARS_PER_IMAGE = 40.0
CONF_THRESHOLD = 0.25

# 密度分 + 绿色覆盖率加权合成长势指数，再按占位版同款分档
DENSITY_WEIGHT = 0.6
VIGOR_CUTS = ((0.45, 5), (0.35, 4), (0.25, 3), (0.15, 2))  # 其余为 1

_COLOR = PlaceholderColorAnalyzer()


class YoloAnalyzer:
    """麦穗检测 + 可选病害分类分析器。模型懒加载，version 带模型文件名便于多版本溯源：
    yolo-<麦穗模型>、yolo-<麦穗模型>+<病害模型>，或无麦穗模型时 color+<病害模型>。"""

    def __init__(self, model_path: str | Path | None, disease_model_path: str | Path | None = None):
        self._model_path = Path(model_path) if model_path else None
        self._disease = RustTileClassifier(disease_model_path) if disease_model_path else None
        if self._model_path is None and self._disease is None:
            raise ValueError("YOLO 分析器至少需要麦穗模型（YOLO_MODEL_PATH）或病害模型（DISEASE_MODEL_PATH）之一")
        ear = f"yolo-{self._model_path.stem}" if self._model_path else "color"
        self.version = f"{ear}+{self._disease.version}" if self._disease else ear
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            if not self._model_path.exists():
                raise RuntimeError(
                    f"YOLO 模型文件不存在：{self._model_path}——"
                    "请先运行 ml/train.py 训练并导出，或将 ANALYZER_BACKEND 切回 placeholder"
                )
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 ultralytics：pip install -r requirements-ml.txt，"
                    "或将 ANALYZER_BACKEND 切回 placeholder"
                ) from exc
            logger.info("加载 YOLO 模型：%s", self._model_path)
            self._model = YOLO(str(self._model_path))
        return self._model

    def _detect(self, image: bytes) -> list[dict[str, Any]]:
        """推理：返回归一化检测 [{"bbox": [x,y,w,h]∈[0,1], "conf": float}]。

        Analyzer 协议输入是 bytes，ultralytics 不直接收——转 PIL 再进 predict。
        """
        import io

        from PIL import Image

        if self._model_path is None:
            return []
        model = self._load()
        pil_image = Image.open(io.BytesIO(image)).convert("RGB")
        results = model.predict(pil_image, conf=CONF_THRESHOLD, verbose=False)
        detections: list[dict[str, Any]] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                xyxyn = box.xyxyn[0].tolist()  # 归一化 [x1,y1,x2,y2]
                detections.append({
                    "bbox": [
                        round(xyxyn[0], 4), round(xyxyn[1], 4),
                        round(xyxyn[2] - xyxyn[0], 4), round(xyxyn[3] - xyxyn[1], 4),
                    ],
                    "conf": round(float(box.conf[0]), 3),
                })
        return detections

    def analyze(self, image: bytes, context: CaptureContext) -> AnalysisResult:
        detections = self._detect(image)
        tiles = self._disease.classify(image) if self._disease else None
        return self.build_result(image, context, detections, tiles)

    def build_result(
        self, image: bytes, context: CaptureContext, detections: list[dict[str, Any]],
        tiles: list[TileProb] | None = None,
    ) -> AnalysisResult:
        """检测 + 颜色信号（+ 病害图块概率）→ 结构化结果。与推理解耦，便于单元测试。"""
        result = self._ear_result(image, context, detections) if self._model_path else _COLOR.analyze(image, context)
        if tiles is None:
            return result
        detection, detail, risk = summarize_tiles(tiles, self._disease.version if self._disease else "disease-model")
        found = list(result.disease_detections or [])
        if detection is not None:
            found.append(detection)
        result.disease_detections = found or None
        result.risk_score = risk  # 风险分来自病害模型，颜色胁迫不再决定它
        result.detail = {**result.detail, **detail}
        return result

    def _ear_result(
        self, image: bytes, context: CaptureContext, detections: list[dict[str, Any]],
    ) -> AnalysisResult:
        stats = image_color_stats(image)
        green_ratio = stats["green_ratio"]
        stress_ratio = stats["stress_ratio"]

        ear_count = len(detections)
        density_score = min(1.0, ear_count / TARGET_EARS_PER_IMAGE)
        vigor_index = DENSITY_WEIGHT * density_score + (1 - DENSITY_WEIGHT) * green_ratio
        vigor_level = next(
            (level for cut, level in VIGOR_CUTS if vigor_index >= cut), 1,
        )

        # NDVI 代理与风险分沿用占位版公式，保证跨 analyzer 版本语义可比
        ndvi_proxy = round(max(-1.0, min(1.0, (green_ratio - 0.18) * 2.4)), 3)
        risk_score = round(
            min(1.0, stress_ratio * 2.5 + max(0.0, 0.22 - green_ratio) * 2.0), 3,
        )

        # v1 模型仅麦穗单类，不产出病害框；胁迫色检出语义与占位版一致（规则保底）
        disease: list[dict] = []
        if stress_ratio >= 0.08:
            disease.append({
                "type": "suspected_stress",
                "label": "叶色异常斑块（疑似胁迫，待人工复核）",
                "confidence": round(min(stress_ratio * 3.0, 0.9), 3),
            })

        return AnalysisResult(
            growth_stage=calendar_growth_stage(context),
            vigor_level=vigor_level,
            ndvi=ndvi_proxy,
            disease_detections=disease or None,
            risk_score=risk_score,
            detail={
                "ear_count": ear_count,
                "avg_conf": round(
                    sum(d["conf"] for d in detections) / ear_count, 3,
                ) if ear_count else None,
                "density_score": round(density_score, 3),
                "vigor_index": round(vigor_index, 3),
                **stats,
                "ndvi_is_proxy": True,
            },
        )
