"""YOLOv8n-cls 条锈病图块分类训练（执行计划 0010）。

用法：
    .venv/bin/python data/prepare_nwrd.py     # 先生成 data/nwrd_cls/
    .venv/bin/python train_rust.py            # 有 GPU 自动使用；CPU 也可训练（图块 224，约 1 小时）
    .venv/bin/python train_rust.py --epochs 3 # 快速管线验证
"""
import argparse
from pathlib import Path

from ultralytics import YOLO

ML_ROOT = Path(__file__).resolve().parent
DATA_DIR = ML_ROOT / "data" / "nwrd_cls"


def has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=64 if has_gpu() else 32)
    ap.add_argument("--name", default="rust-cls-v1")
    args = ap.parse_args()
    if not (DATA_DIR / "train").exists():
        raise SystemExit(f"找不到 {DATA_DIR}——先运行 data/prepare_nwrd.py")

    device = 0 if has_gpu() else "cpu"
    print(f"设备：{'GPU' if has_gpu() else 'CPU'}")
    model = YOLO("yolov8n-cls.pt")  # ImageNet 预训练权重，自动下载
    model.train(
        data=str(DATA_DIR),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=224,
        device=device,
        workers=4,
        project=str(ML_ROOT / "runs"),
        name=args.name,
        exist_ok=True,
        patience=6,
        seed=42,
        deterministic=True,
    )
    print(f"训练完成：{ML_ROOT / 'runs' / args.name / 'weights' / 'best.pt'}")
    print("下一步：.venv/bin/python eval_rust.py")
