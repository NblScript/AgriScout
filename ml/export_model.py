"""训练产物导出：best.pt → backend/models/wheat-yolo-v{N}.pt。

用法：
    .venv/bin/python export_model.py            # 自动找 runs/wheat-v1/weights/best.pt
    .venv/bin/python export_model.py --run wheat-v2
导出后设置 backend/.env：ANALYZER_BACKEND=yolo、YOLO_MODEL_PATH=./models/wheat-yolo-v{N}.pt
"""
import argparse
import re
import shutil
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
BACKEND_MODELS = REPO_ROOT / "backend" / "models"


def next_version() -> int:
    existing = [int(m.group(1)) for p in BACKEND_MODELS.glob("wheat-yolo-v*.pt")
                if (m := re.search(r"v(\d+)", p.name))]
    return max(existing, default=0) + 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="wheat-v1", help="runs/ 下的实验目录名")
    args = ap.parse_args()

    best = ML_ROOT / "runs" / args.run / "weights" / "best.pt"
    if not best.exists():
        raise SystemExit(f"找不到训练产物：{best}——先运行 train.py")

    BACKEND_MODELS.mkdir(exist_ok=True)
    version = next_version()
    target = BACKEND_MODELS / f"wheat-yolo-v{version}.pt"
    shutil.copy(best, target)
    size_mb = target.stat().st_size / 1e6
    print(f"已导出：{target}（{size_mb:.1f} MB）")
    print("启用方式（backend/.env）：")
    print(f"  ANALYZER_BACKEND=yolo")
    print(f"  YOLO_MODEL_PATH=./models/{target.name}")
