"""Global Wheat Head 数据集准备：GitHub tarball → train/val 切分。

用法：
    .venv/bin/python data/prepare_gwd.py

数据源：DhruvMakwana/Global-Wheat-Detection（GWD 2020 完整镜像，3422 图）。
该镜像 labels/ 已是 YOLO 归一化格式（class 0 = wheat_head），本脚本只做 90/10 切分。
下载走 codeload tarball（git clone 会被 GFW 掐断大流量 TLS；kagglehub 匿名 403；Zenodo/HF 不可达）。
"""
import random
import shutil

import tarfile
import urllib.request
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ML_ROOT / "data" / "gwd_yolo"
RAW_ROOT = ML_ROOT / "data" / "gwd_raw"
TARBALL_URL = "https://codeload.github.com/DhruvMakwana/Global-Wheat-Detection/tar.gz/refs/heads/master"

random.seed(42)


def ensure_raw() -> None:
    train = RAW_ROOT / "data" / "train"
    if train.exists() and len(list(train.glob("*.jpg"))) > 3000:
        return
    RAW_ROOT.parent.mkdir(parents=True, exist_ok=True)
    archive = ML_ROOT / "data" / "gwd.tar.gz"
    if not archive.exists():
        print("下载 GWD tarball（约 650MB）…")
        urllib.request.urlretrieve(TARBALL_URL, archive)
    print("解压…")
    with tarfile.open(archive) as tf:
        tf.extractall(RAW_ROOT.parent)
    (RAW_ROOT.parent / "Global-Wheat-Detection-master").rename(RAW_ROOT)
    archive.unlink()


def main() -> None:
    ensure_raw()
    img_dir = RAW_ROOT / "data" / "train"
    lbl_dir = RAW_ROOT / "data" / "labels"
    ids = sorted(p.stem for p in img_dir.glob("*.jpg") if (lbl_dir / f"{p.stem}.txt").exists())
    print(f"图片+标注对：{len(ids)}")
    assert len(ids) > 3000, f"镜像不完整：仅 {len(ids)} 对"

    random.shuffle(ids)
    val_n = max(1, len(ids) // 10)
    splits = {"train": ids[val_n:], "val": ids[:val_n]}

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    for split, split_ids in splits.items():
        (OUT_ROOT / "images" / split).mkdir(parents=True)
        (OUT_ROOT / "labels" / split).mkdir(parents=True)
        for img_id in split_ids:
            shutil.copy(img_dir / f"{img_id}.jpg", OUT_ROOT / "images" / split / f"{img_id}.jpg")
            shutil.copy(lbl_dir / f"{img_id}.txt", OUT_ROOT / "labels" / split / f"{img_id}.txt")
        print(f"{split}: {len(split_ids)}")

    (OUT_ROOT / "data.yaml").write_text(
        f"path: {OUT_ROOT}\ntrain: images/train\nval: images/val\n"
        "nc: 1\nnames: [wheat_head]\n"
    )
    print(f"完成 → {OUT_ROOT}")


if __name__ == "__main__":
    main()
