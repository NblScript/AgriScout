"""条锈病图块分类（rust-cls，执行计划 0010）：照片切网格 → 每块锈病概率 → 汇总检出与风险分。

模型由 ml/train_rust.py 在 NWRD 公开田间数据集（Zenodo DOI 10.5281/zenodo.21672928，CC-BY-4.0）上训练，
ml/export_model.py --kind rust 导出到 backend/models/（gitignore），同名 .json 说明文件记录数据来源、测试指标与局限。

网格口径与 ml/eval_rust.py 的推理几何评估一致：照片短边超过 480 先缩到 480（小车默认上传 640×480），
短边切 3 格、正方形图块、最后一行/列贴边补齐。ultralytics 为可选依赖：只在推理时加载。
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GRID_SHORT = 3
INFER_SHORT_SIDE = 480
RUST_THRESHOLD = 0.5
RUST_LABEL = "疑似条锈病（模型检出，待人工复核）"


def tile_boxes(width: int, height: int, grid_short: int = GRID_SHORT) -> list[tuple[int, int, int, int]]:
    """覆盖整图的正方形网格 (x, y, w, h)：短边 grid_short 格，最后一行/列贴边。"""
    size = min(width, height) // grid_short
    if size <= 0:
        return []

    def starts(length: int) -> list[int]:
        out = list(range(0, length - size + 1, size))
        if out[-1] != length - size:
            out.append(length - size)
        return out

    return [(x, y, size, size) for y in starts(height) for x in starts(width)]


@dataclass(frozen=True, slots=True)
class TileProb:
    box: tuple[float, float, float, float]  # 归一化 (x, y, w, h)
    prob: float                             # 锈病概率


def summarize_tiles(tiles: list[TileProb], model_version: str) -> tuple[dict[str, Any] | None, dict[str, Any], float]:
    """图块概率 → (汇总检出 | None, detail 字段, 风险分)。风险分取最高图块概率：病斑哪怕只占一格也要复核。"""
    if not tiles:
        return None, {"disease_model": model_version, "tiles": 0}, 0.0
    max_prob = max(t.prob for t in tiles)
    positives = [t for t in tiles if t.prob >= RUST_THRESHOLD]
    detail = {
        "disease_model": model_version,
        "tiles": len(tiles),
        "rust_tiles": len(positives),
        "rust_tile_ratio": round(len(positives) / len(tiles), 3),
        "rust_prob_max": round(max_prob, 3),
        "risk_source": "disease_model",
    }
    detection = None
    if positives:
        detection = {
            "type": "stripe_rust",
            "label": RUST_LABEL,
            "confidence": round(max_prob, 3),
            "area_ratio": detail["rust_tile_ratio"],
            "boxes": [[round(v, 4) for v in t.box] for t in positives],
            "model": model_version,
        }
    return detection, detail, round(max_prob, 3)


class RustTileClassifier:
    """条锈病图块分类器。模型懒加载；version 为模型文件名（如 rust-cls-v1）。"""

    def __init__(self, model_path: str | Path):
        self._model_path = Path(model_path)
        self.version = self._model_path.stem
        self._model: Any | None = None
        self._rust_index: int | None = None

    def _load(self) -> Any:
        if self._model is None:
            if not self._model_path.exists():
                raise RuntimeError(
                    f"病害模型文件不存在：{self._model_path}——请先运行 ml/train_rust.py 训练并用 "
                    "ml/export_model.py --kind rust 导出，或清空 DISEASE_MODEL_PATH"
                )
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError("未安装 ultralytics：pip install -r requirements-ml.txt，或清空 DISEASE_MODEL_PATH") from exc
            model = YOLO(str(self._model_path))
            names = {int(i): n for i, n in model.names.items()}
            if "rust" not in names.values():
                raise RuntimeError(f"{self._model_path.name} 不是锈病分类模型：类别为 {sorted(names.values())}")
            logger.info("加载病害模型：%s", self._model_path)
            self._rust_index = next(i for i, n in names.items() if n == "rust")
            self._model = model
        return self._model

    def _predict(self, crops: list[Any]) -> list[float]:
        model = self._load()
        results = model.predict(crops, imgsz=224, verbose=False)
        return [float(r.probs.data[self._rust_index]) for r in results]

    def classify(self, image: bytes) -> list[TileProb]:
        from PIL import Image

        pil = Image.open(io.BytesIO(image)).convert("RGB")
        short = min(pil.size)
        if short > INFER_SHORT_SIDE:
            scale = INFER_SHORT_SIDE / short
            pil = pil.resize((round(pil.width * scale), round(pil.height * scale)), Image.BILINEAR)
        boxes = tile_boxes(pil.width, pil.height)
        if not boxes:
            return []
        probs = self._predict([pil.crop((x, y, x + w, y + h)) for x, y, w, h in boxes])
        return [
            TileProb((x / pil.width, y / pil.height, w / pil.width, h / pil.height), p)
            for (x, y, w, h), p in zip(boxes, probs)
        ]
