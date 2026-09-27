"""NWRD 条锈病数据集准备：Zenodo 下载校验 → 掩膜切块打标签 → 按整图划分（执行计划 0010）。

用法：
    .venv/bin/python data/prepare_nwrd.py              # 下载（已存在则跳过）并生成 data/nwrd_cls/
    .venv/bin/python data/prepare_nwrd.py --zip 路径    # 用手动下载好的 NWRD.zip

数据源：NUST Wheat Rust Disease（NWRD）v1.0，Zenodo DOI 10.5281/zenodo.21672928，CC-BY-4.0，
Anwar & Shafait, Sensors 2023, 23(15):6942。100 张自然田间条件的多叶片图像 + 条锈病二值掩膜，官方已分训练/测试集。

产物（ultralytics 分类数据集格式）：
    data/nwrd_cls/{train,val,test}/{healthy,rust}/*.jpg   224×224 图块
    data/nwrd_cls/manifest.json                            来源、校验值、口径、各划分的整图名单与图块数
    data/nwrd_cls/test_images.json                         测试集整图与掩膜路径（eval_rust.py 做整图级评估用）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import urllib.request
import zipfile
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = ML_ROOT / "data" / "nwrd_raw"
OUT_ROOT = ML_ROOT / "data" / "nwrd_cls"

SOURCE = {
    "name": "NUST Wheat Rust Disease (NWRD) v1.0",
    "doi": "10.5281/zenodo.21672928",
    "license": "CC-BY-4.0",
    "citation": "Anwar H., Shafait F. The NWRD Dataset: An Open-Source Annotated Segmentation Dataset "
                "of Diseased Wheat Crop. Sensors 2023, 23(15):6942.",
    "url": "https://zenodo.org/api/records/21672928/files/NWRD.zip/content",
    "md5": "7b9193efebe1ed8c60b10c9f05d11e14",
}

# 标签口径：图块内锈病像素占比 ≥ RUST_MIN 记锈病，为 0 记健康，之间的边界样本不用。
# NWRD 掩膜只标孢子堆像素，整图占比中位数仅 0.35%；短边 1/3 的图块里 0.5% 约为 94×94 像素的可见病斑
RUST_MIN = 0.005
# 多尺度：图块边长 = 整图短边 × 比例。1/3 与平台推理的网格一致（短边 3 格），1/6 覆盖更近的拍摄距离
SCALES = (1 / 3, 1 / 6)
PATCH_PX = 224
VAL_FRACTION = 0.1
HEALTHY_PER_RUST = 2.0  # 训练集健康:锈病 上限，缓解类别不平衡
SEED = 42


def md5sum(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def patch_boxes(width: int, height: int, size: int, stride: int) -> list[tuple[int, int, int, int]]:
    """覆盖整图的正方形图块 (x, y, w, h)；最后一行/列贴边，保证边缘也被切到。"""
    if size > min(width, height):
        return []

    def starts(length: int) -> list[int]:
        out = list(range(0, length - size + 1, stride))
        if out[-1] != length - size:
            out.append(length - size)
        return out

    return [(x, y, size, size) for y in starts(height) for x in starts(width)]


def label_for(rust_ratio: float) -> str | None:
    if rust_ratio >= RUST_MIN:
        return "rust"
    if rust_ratio == 0:
        return "healthy"
    return None


def split_train_val(names: list[str], fraction: float = VAL_FRACTION, seed: int = SEED) -> tuple[list[str], list[str]]:
    """按整图留出验证集（同一张图的图块不跨划分）。"""
    ordered = sorted(names)
    rng = random.Random(seed)
    n_val = max(1, round(len(ordered) * fraction))
    val = sorted(rng.sample(ordered, n_val))
    return [n for n in ordered if n not in val], val


def ensure_zip(zip_path: Path) -> Path:
    if zip_path.exists() and md5sum(zip_path) == SOURCE["md5"]:
        return zip_path
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 {SOURCE['url']}（约 609 MB）…")
    urllib.request.urlretrieve(SOURCE["url"], zip_path)
    actual = md5sum(zip_path)
    if actual != SOURCE["md5"]:
        raise SystemExit(f"MD5 不符：{actual} ≠ {SOURCE['md5']}——文件损坏或来源变化，已停止")
    return zip_path


def find_split_dirs(root: Path) -> dict[str, Path]:
    """在解压目录里找官方 train/test 划分（容忍外层多一级目录）。"""
    found = {}
    for split in ("train", "test"):
        hits = [p for p in root.rglob(split) if (p / "images").is_dir() and (p / "masks").is_dir()]
        if not hits:
            raise SystemExit(f"解压目录里找不到 {split}/images 与 {split}/masks")
        found[split] = min(hits, key=lambda p: len(p.parts))
    return found


def size_mismatch(image: Path, mask: Path) -> bool:
    """只读文件头比较尺寸。NWRD v1.0 中 train/101.jpg 为 3612×3456、掩膜为 3593×3435，
    裁剪偏移无从得知，硬对齐会让标签错位，因此整张排除并记入清单。"""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(image) as img, Image.open(mask) as msk:
        return img.size != msk.size


def mask_for(image: Path, masks_dir: Path) -> Path:
    for candidate in (masks_dir / f"{image.stem}.png", *masks_dir.glob(f"{image.stem}.*")):
        if candidate.exists():
            return candidate
    raise SystemExit(f"找不到 {image.name} 的掩膜")


def cut_image(image_path: Path, mask_path: Path, out_split: Path) -> dict[str, int]:
    """整图 → 多尺度图块，按掩膜打标签后缩放保存；返回各标签数量。"""
    import numpy as np
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None  # 原图 4000×6016，超过 PIL 默认的解压炸弹阈值
    image = Image.open(image_path).convert("RGB")
    mask = np.asarray(Image.open(mask_path).convert("L")) > 127
    if mask.shape != (image.height, image.width):
        raise SystemExit(f"{image_path.name} 图像与掩膜尺寸不一致")
    counts = {"rust": 0, "healthy": 0, "skipped": 0}
    short = min(image.width, image.height)
    for scale in SCALES:
        size = int(short * scale)
        for x, y, w, h in patch_boxes(image.width, image.height, size, stride=size // 2):
            label = label_for(float(mask[y:y + h, x:x + w].mean()))
            if label is None:
                counts["skipped"] += 1
                continue
            target = out_split / label / f"{image_path.stem}_s{size}_{x}_{y}.jpg"
            image.crop((x, y, x + w, y + h)).resize((PATCH_PX, PATCH_PX), Image.BILINEAR).save(target, quality=92)
            counts[label] += 1
    return counts


def balance_healthy(split_dir: Path, ratio: float = HEALTHY_PER_RUST, seed: int = SEED) -> int:
    """训练集健康图块多于 ratio × 锈病时随机删去多余部分，返回删除数。"""
    rust = len(list((split_dir / "rust").glob("*.jpg")))
    healthy = sorted((split_dir / "healthy").glob("*.jpg"))
    keep = int(rust * ratio)
    if len(healthy) <= keep:
        return 0
    drop = random.Random(seed).sample(healthy, len(healthy) - keep)
    for path in drop:
        path.unlink()
    return len(drop)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="准备 NWRD 条锈病图块分类数据集")
    ap.add_argument("--zip", type=Path, default=RAW_ROOT / "NWRD.zip")
    args = ap.parse_args(argv)

    zip_path = ensure_zip(args.zip)
    extract_root = RAW_ROOT / "extracted"
    if not extract_root.exists():
        print("解压…")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_root)
    splits = find_split_dirs(extract_root)

    excluded: list[dict[str, str]] = []

    def usable(split: str) -> list[Path]:
        images = []
        for path in sorted(p for p in (splits[split] / "images").iterdir() if p.is_file()):
            if size_mismatch(path, mask_for(path, splits[split] / "masks")):
                excluded.append({"split": split, "image": path.name, "reason": "图像与掩膜尺寸不一致"})
                print(f"  排除 {split}/{path.name}：图像与掩膜尺寸不一致")
                continue
            images.append(path)
        return images

    train_images, test_images = usable("train"), usable("test")
    train_names, val_names = split_train_val([p.name for p in train_images])
    plan = {
        "train": [p for p in train_images if p.name in train_names],
        "val": [p for p in train_images if p.name in val_names],
        "test": test_images,
    }
    masks_dir = {"train": splits["train"] / "masks", "val": splits["train"] / "masks", "test": splits["test"] / "masks"}

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    manifest = {"source": SOURCE, "rust_min_ratio": RUST_MIN, "scales_of_short_side": list(SCALES),
                "patch_px": PATCH_PX, "healthy_per_rust_train": HEALTHY_PER_RUST, "seed": SEED,
                "excluded_images": excluded, "splits": {}}
    for split, images in plan.items():
        out_split = OUT_ROOT / split
        for label in ("rust", "healthy"):
            (out_split / label).mkdir(parents=True, exist_ok=True)
        totals = {"rust": 0, "healthy": 0, "skipped": 0}
        for i, image in enumerate(images, start=1):
            counts = cut_image(image, mask_for(image, masks_dir[split]), out_split)
            totals = {k: totals[k] + counts[k] for k in totals}
            print(f"  [{split}] {i}/{len(images)} {image.name} 锈病 {counts['rust']} 健康 {counts['healthy']}")
        dropped = balance_healthy(out_split) if split == "train" else 0
        totals["healthy"] -= dropped
        manifest["splits"][split] = {"images": [p.name for p in images], "patches": totals,
                                     "healthy_dropped_for_balance": dropped}
        print(f"[{split}] 整图 {len(images)}，图块 锈病 {totals['rust']} / 健康 {totals['healthy']}（边界跳过 {totals['skipped']}）")

    (OUT_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_ROOT / "test_images.json").write_text(json.dumps(
        [{"image": str(p), "mask": str(mask_for(p, masks_dir["test"]))} for p in test_images],
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：{OUT_ROOT}")


if __name__ == "__main__":
    main()
