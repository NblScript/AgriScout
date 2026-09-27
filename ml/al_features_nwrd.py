"""H3 真实数据验证的特征导出（执行计划 0011）：NWRD 图块 → 冻结特征 → PCA → 样本文件。

特征用 ImageNet 预训练、未在 NWRD 上训练过的 YOLOv8n-cls 提取（不用 rust-cls-v1：它见过全部训练标签，会泄漏），
PCA 只在候选池上拟合（无监督）。候选池从官方训练集图块按固定种子抽样，测试集为官方测试集全部图块。
后端 app/tools/al_replay_images.py 读取本文件，用与仿真相同的 H3 实现对比选样策略。

用法：
    .venv/bin/python al_features_nwrd.py              # 产物 data/nwrd_cls/al_features.json（不入库）
    .venv/bin/python al_features_nwrd.py --pool 4000 --dims 32
"""
import argparse
import json
import random
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from ultralytics import YOLO

ML_ROOT = Path(__file__).resolve().parent
DATA = ML_ROOT / "data" / "nwrd_cls"


def patches(split: str) -> list[tuple[Path, int]]:
    out = []
    for label, y in (("healthy", 0), ("rust", 1)):
        out += [(p, y) for p in sorted((DATA / split / label).glob("*.jpg"))]
    return out


def region_of(path: Path) -> str:
    """图块文件名 <整图>_s<边长>_<x>_<y>.jpg → 来源整图。"""
    return path.stem.split("_s")[0]


def embed(model: YOLO, paths: list[Path]) -> np.ndarray:
    vecs = []
    for start in range(0, len(paths), 64):
        for v in model.embed([str(p) for p in paths[start:start + 64]], imgsz=224, verbose=False):
            vecs.append(v.detach().cpu().numpy().ravel())
        print(f"  特征 {min(start + 64, len(paths))}/{len(paths)}", end="\r")
    print()
    return np.stack(vecs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=4000, help="候选池抽样图块数")
    ap.add_argument("--dims", type=int, default=32, help="PCA 维数")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    if not (DATA / "train").exists():
        raise SystemExit(f"找不到 {DATA}——先运行 data/prepare_nwrd.py")

    pool = random.Random(args.seed).sample(patches("train"), args.pool)
    test = patches("test")
    model = YOLO("yolov8n-cls.pt")  # ImageNet 预训练，未见过 NWRD
    print(f"候选池 {len(pool)} 块（锈病 {sum(y for _, y in pool)}），测试集 {len(test)} 块（锈病 {sum(y for _, y in test)}）")
    x_pool, x_test = embed(model, [p for p, _ in pool]), embed(model, [p for p, _ in test])
    pca = PCA(n_components=args.dims, random_state=args.seed).fit(x_pool)
    z_pool, z_test = pca.transform(x_pool), pca.transform(x_test)
    names = [f"pc{i:02d}" for i in range(args.dims)]
    samples = (
        [{"region": region_of(p), "fold": 1, "label": y, "features": [round(float(v), 5) for v in z]}
         for (p, y), z in zip(pool, z_pool)]
        + [{"region": region_of(p), "fold": 0, "label": y, "features": [round(float(v), 5) for v in z]}
           for (p, y), z in zip(test, z_test)]
    )
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    doc = {
        "schema": "agriscout.al-image-samples.v1",
        "source": manifest["source"],
        "embedding_model": "yolov8n-cls.pt（ImageNet 预训练，未在 NWRD 上训练）",
        "pca": {"dims": args.dims, "explained_variance": round(float(pca.explained_variance_ratio_.sum()), 4),
                "fit_on": "候选池"},
        "pool_seed": args.seed, "test_fold": 0, "names": names, "samples": samples,
    }
    out = DATA / "al_features.json"
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"PCA {args.dims} 维，解释方差 {doc['pca']['explained_variance']}；写出 {out}")


if __name__ == "__main__":
    main()
