"""L1 识别：YOLOv8n 麦穗检测 + 颜色统计混合分析（主计划 §8.1 级别 L1）。

检测信号：单类 wheat_head bbox → 穗数密度估长势（0.5m 高密度采样的核心优势）；
颜色信号：复用 base.py 的 HSV 统计，绿色比率→NDVI 代理、胁迫色→风险分。
日历法生育期与颜色胁迫检出保持与占位版一致的语义，规则引擎零改动。

模型由 ml/train.py 训练产出（Global Wheat Head 公开集），真车照片到位后
换数据重训，本模块协议不变。ultralytics 为可选依赖：仅 backend=yolo 时加载。
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

logger = logging.getLogger(__name__)

# GWD 图均穗数约 44；以此为饱和密度基准换算密度分（粗标定，真车数据后修正）
TARGET_EARS_PER_IMAGE = 40.0
CONF_THRESHOLD = 0.25

# 密度分 + 绿色覆盖率加权合成长势指数，再按占位版同款分档
DENSITY_WEIGHT = 0.6
VIGOR_CUTS = ((0.45, 5), (0.35, 4), (0.25, 3), (0.15, 2))  # 其余为 1


class YoloAnalyzer:
    """麦穗检测分析器。模型懒加载，version 带模型文件名便于多版本溯源。"""

    def __init__(self, model_path: str | Path):
        self._model_path = Path(model_path)
        self.version = f"yolo-{self._model_path.stem}"
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
        return self.build_result(image, context, detections)

    def build_result(
        self, image: bytes, context: CaptureContext, detections: list[dict[str, Any]],
    ) -> AnalysisResult:
        """检测 + 颜色信号 → 结构化结果。与推理解耦，便于单元测试。"""
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
