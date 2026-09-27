"""训练产物导出：best.pt → backend/models/（gitignore，红线 7）。

用法：
    .venv/bin/python export_model.py                        # 麦穗检测：runs/wheat-v1 → wheat-yolo-v{N}.pt
    .venv/bin/python export_model.py --run wheat-v2
    .venv/bin/python export_model.py --kind rust            # 条锈病分类：runs/rust-cls-v1 → rust-cls-v{N}.pt + 同名 .json
导出后设置 backend/.env：ANALYZER_BACKEND=yolo，以及 YOLO_MODEL_PATH / DISEASE_MODEL_PATH 指向导出文件。

条锈病模型的 .json 说明文件记录数据来源与许可证、标签口径、划分、测试集指标（eval_rust.py 产出）、
推理网格、文件 SHA-256 与局限，供答辩和追溯；没有 eval.json 时拒绝导出（未经测试集评估的模型不发布）。
"""
import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent  # export_model.py 位于 ml/ 一级目录
REPO_ROOT = ML_ROOT.parent
BACKEND_MODELS = REPO_ROOT / "backend" / "models"

KINDS = {
    "wheat": {"run": "wheat-v1", "prefix": "wheat-yolo-v", "env": "YOLO_MODEL_PATH", "train": "train.py"},
    "rust": {"run": "rust-cls-v1", "prefix": "rust-cls-v", "env": "DISEASE_MODEL_PATH", "train": "train_rust.py"},
}
RUST_LIMITATIONS = [
    "训练数据为 NWRD：巴基斯坦田间近距离多叶片图像、单一病害（条锈病），与小车俯拍冠层存在拍摄距离与品种的域差",
    "图块标签由掩膜换算（锈病像素占比 ≥ 0.5% 记锈病、为 0 记健康），边界样本未参与训练",
    "输出为候选检出，须人工复核；小车照片到位后应以自采标注数据微调并重新评估",
]


def next_version(prefix: str) -> int:
    existing = [int(m.group(1)) for p in BACKEND_MODELS.glob(f"{prefix}*.pt")
                if (m := re.search(r"v(\d+)\.pt$", p.name))]
    return max(existing, default=0) + 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rust_card(run: str, target: Path) -> dict:
    eval_path = ML_ROOT / "runs" / run / "eval.json"
    if not eval_path.exists():
        raise SystemExit(f"找不到 {eval_path}——先运行 eval_rust.py --run {run}（未经测试集评估的模型不导出）")
    report = json.loads(eval_path.read_text(encoding="utf-8"))
    manifest = report["manifest"]
    image_level = {k: v for k, v in report["image_level"].items() if k != "per_image"}
    return {
        "model": target.stem,
        "file": target.name,
        "sha256": sha256(target),
        "task": "条锈病图块二分类（healthy / rust），YOLOv8n-cls，输入 224×224",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_run": run,
        "data": {
            "source": manifest["source"],
            "rust_min_ratio": manifest["rust_min_ratio"],
            "scales_of_short_side": manifest["scales_of_short_side"],
            "excluded_images": manifest["excluded_images"],
            "splits": {k: {"images": len(v["images"]), "patches": v["patches"]} for k, v in manifest["splits"].items()},
        },
        "inference": {"grid_short": report["inference_geometry"]["grid_short"],
                      "short_side_px": report["inference_geometry"]["short_side_px"],
                      "threshold": report["threshold"]},
        "test_metrics": {"patch_level": report["patch_level"],
                         "inference_geometry": report["inference_geometry"]["tiles"],
                         "image_level": image_level},
        "limitations": RUST_LIMITATIONS,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=sorted(KINDS), default="wheat")
    ap.add_argument("--run", default=None, help="runs/ 下的实验目录名（缺省按 --kind）")
    args = ap.parse_args()
    kind = KINDS[args.kind]
    run = args.run or kind["run"]

    best = ML_ROOT / "runs" / run / "weights" / "best.pt"
    if not best.exists():
        raise SystemExit(f"找不到训练产物：{best}——先运行 {kind['train']}")

    BACKEND_MODELS.mkdir(exist_ok=True)
    target = BACKEND_MODELS / f"{kind['prefix']}{next_version(kind['prefix'])}.pt"
    shutil.copy(best, target)
    if args.kind == "rust":
        try:
            card = rust_card(run, target)
        except SystemExit:
            target.unlink()
            raise
        target.with_suffix(".json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"说明文件：{target.with_suffix('.json')}")
    print(f"已导出：{target}（{target.stat().st_size / 1e6:.1f} MB）")
    print("启用方式（backend/.env）：")
    print("  ANALYZER_BACKEND=yolo")
    print(f"  {kind['env']}=./models/{target.name}")
