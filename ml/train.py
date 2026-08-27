"""YOLOv8n 麦穗检测训练。

用法：
    .venv/bin/python train.py                 # 全量数据训练
    .venv/bin/python train.py --epochs 15     # 快速管线验证
"""
import argparse
from pathlib import Path

from ultralytics import YOLO

ML_ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = ML_ROOT / "data" / "gwd_yolo" / "data.yaml"


def has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=16 if has_gpu() else 8)
    args = ap.parse_args()

    device = 0 if has_gpu() else "cpu"
    print(f"设备：{'GPU ' + __import__('torch').cuda.get_device_name(0) if has_gpu() else 'CPU'}")

    model = YOLO("yolov8n.pt")  # COCO 预训练权重，自动下载
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        batch=args.batch,
        device=device,
        imgsz=640,
        workers=4,
        project=str(ML_ROOT / "runs"),
        name="wheat-v1",
        exist_ok=True,
        patience=10,
    )
    print(f"训练完成：{ML_ROOT / 'runs' / 'wheat-v1' / 'weights' / 'best.pt'}")
