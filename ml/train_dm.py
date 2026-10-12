"""黄瓜霜霉病整叶分类训练（执行计划 0019）。

用法：
    .venv/bin/python data/prepare_dm.py                    # 先生成 data/dm_cls/
    .venv/bin/python train_dm.py                           # 默认 yolov8n-cls，有 GPU 自动使用
    .venv/bin/python train_dm.py --model yolo11n-cls.pt --name dm-cls-v1-y11n   # 换结构比较，只按验证集选
    .venv/bin/python train_dm.py --epochs 2                # 快速管线验证
"""
import argparse
from pathlib import Path

from ultralytics import YOLO

ML_ROOT = Path(__file__).resolve().parent
DATA_DIR = ML_ROOT / "data" / "dm_cls"


def has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolov8n-cls.pt", help="ImageNet 预训练权重，自动下载")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=128 if has_gpu() else 32)
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--name", default="dm-cls-v1")
    args = ap.parse_args()
    if not (DATA_DIR / "train").exists():
        raise SystemExit(f"找不到 {DATA_DIR}——先运行 data/prepare_dm.py")

    device = 0 if has_gpu() else "cpu"
    print(f"设备：{'GPU' if has_gpu() else 'CPU'}，模型 {args.model}")
    model = YOLO(args.model)
    model.train(
        data=str(DATA_DIR),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=device,
        workers=8 if has_gpu() else 4,
        project=str(ML_ROOT / "runs"),
        name=args.name,
        exist_ok=True,
        patience=12,
        seed=42,
        deterministic=True,
    )
    print(f"训练完成：{ML_ROOT / 'runs' / args.name / 'weights' / 'best.pt'}")
    print(f"下一步：.venv/bin/python eval_dm.py --run {args.name} --split val（比较结构），选定后 --split test 跑一次")
