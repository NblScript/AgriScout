"""rust-cls 测试集评估（执行计划 0010）：只用 NWRD 官方测试集，训练与选模均未见过。

两层指标：
1. 图块级：data/nwrd_cls/test 的 224 图块（与训练同口径切块）；
2. 推理几何：把测试整图缩到小车照片分辨率（短边 480），按平台同样的网格（短边 3 格、正方形图块、贴边补齐）
   逐块推理，与全分辨率掩膜算出的图块真值比对；另算整图检出率、面积比例与掩膜锈病占比的秩相关。
   网格口径须与 backend/app/services/analysis/disease_classifier.py 的 tile_boxes 保持一致。

用法：
    .venv/bin/python eval_rust.py                  # 默认 runs/rust-cls-v1/weights/best.pt
    .venv/bin/python eval_rust.py --run rust-cls-v2
结果写入 runs/<run>/eval.json，export_model.py --kind rust 会把它并入模型说明文件。
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from ultralytics import YOLO

ML_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ML_ROOT / "data"))
from prepare_nwrd import OUT_ROOT, RUST_MIN, label_for, patch_boxes  # noqa: E402

THRESHOLD = 0.5
INFER_SHORT_SIDE = 480  # 小车采集端默认上传 640×480
GRID_SHORT = 3


def grid_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    size = min(width, height) // GRID_SHORT
    return patch_boxes(width, height, size, stride=size)


def rust_probs(model: YOLO, images: list) -> np.ndarray:
    rust_idx = next(i for i, name in model.names.items() if name == "rust")
    probs = []
    for start in range(0, len(images), 64):
        for r in model.predict(images[start:start + 64], imgsz=224, verbose=False):
            probs.append(float(r.probs.data[rust_idx]))
    return np.array(probs)


def binary_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    pred = (p >= THRESHOLD).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "n": int(len(y)), "positives": int(y.sum()),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y, p)), 4) if 0 < y.sum() < len(y) else None,
        "pr_auc": round(float(average_precision_score(y, p)), 4) if y.sum() else None,
        "confusion": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)},
    }


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return round(float(np.corrcoef(ra, rb)[0, 1]), 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="rust-cls-v1")
    args = ap.parse_args()
    weights = ML_ROOT / "runs" / args.run / "weights" / "best.pt"
    if not weights.exists():
        raise SystemExit(f"找不到 {weights}——先运行 train_rust.py")
    model = YOLO(str(weights))
    Image.MAX_IMAGE_PIXELS = None

    # 1) 图块级
    paths, labels = [], []
    for label, y in (("healthy", 0), ("rust", 1)):
        files = sorted((OUT_ROOT / "test" / label).glob("*.jpg"))
        paths += [str(f) for f in files]
        labels += [y] * len(files)
    patch = binary_metrics(np.array(labels), rust_probs(model, paths))
    print(f"图块级（{patch['n']} 块，锈病 {patch['positives']}）：P={patch['precision']} R={patch['recall']} "
          f"F1={patch['f1']} ROC-AUC={patch['roc_auc']} PR-AUC={patch['pr_auc']}")

    # 2) 推理几何
    tile_y, tile_p, per_image = [], [], []
    ambiguous = 0
    for item in json.loads((OUT_ROOT / "test_images.json").read_text(encoding="utf-8")):
        image = Image.open(item["image"]).convert("RGB")
        mask = np.asarray(Image.open(item["mask"]).convert("L")) > 127
        scale = INFER_SHORT_SIDE / min(image.size)
        small = image.resize((round(image.width * scale), round(image.height * scale)), Image.BILINEAR)
        boxes = grid_boxes(small.width, small.height)
        probs = rust_probs(model, [small.crop((x, y, x + w, y + h)) for x, y, w, h in boxes])
        truth = []
        for x, y, w, h in boxes:
            x0, y0 = int(x / scale), int(y / scale)
            x1, y1 = min(mask.shape[1], int((x + w) / scale)), min(mask.shape[0], int((y + h) / scale))
            truth.append(label_for(float(mask[y0:y1, x0:x1].mean())))
        for t, p in zip(truth, probs):
            if t is None:
                ambiguous += 1
                continue
            tile_y.append(1 if t == "rust" else 0)
            tile_p.append(p)
        per_image.append({
            "image": Path(item["image"]).name, "tiles": len(boxes),
            "rust_ratio_mask": round(float(mask.mean()), 5),
            "rust_tile_ratio_pred": round(float((probs >= THRESHOLD).mean()), 4),
            "max_prob": round(float(probs.max()), 4),
        })
    tiles = binary_metrics(np.array(tile_y), np.array(tile_p))
    tiles["ambiguous_excluded"] = ambiguous
    detected = sum(1 for r in per_image if r["max_prob"] >= THRESHOLD)
    image_level = {
        "images": len(per_image), "detected": detected,
        "note": "NWRD 每张图都有锈病，整图级只能衡量检出率",
        "spearman_area_vs_mask": spearman([r["rust_tile_ratio_pred"] for r in per_image],
                                          [r["rust_ratio_mask"] for r in per_image]),
        "per_image": per_image,
    }
    print(f"推理几何（短边 {INFER_SHORT_SIDE}，{GRID_SHORT} 格网格）：{tiles['n']} 块（边界 {ambiguous} 块不计）"
          f" P={tiles['precision']} R={tiles['recall']} F1={tiles['f1']} ROC-AUC={tiles['roc_auc']}")
    print(f"整图检出 {detected}/{len(per_image)}；面积比例与掩膜占比秩相关 {image_level['spearman_area_vs_mask']}")

    report = {
        "run": args.run, "threshold": THRESHOLD, "rust_min_ratio": RUST_MIN,
        "patch_level": patch,
        "inference_geometry": {"short_side_px": INFER_SHORT_SIDE, "grid_short": GRID_SHORT, "tiles": tiles},
        "image_level": image_level,
        "manifest": json.loads((OUT_ROOT / "manifest.json").read_text(encoding="utf-8")),
    }
    out = ML_ROOT / "runs" / args.run / "eval.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[报告] {out}")


if __name__ == "__main__":
    main()
