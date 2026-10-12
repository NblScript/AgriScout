"""黄瓜霜霉病公开数据准备：下载 → 读许可 → 只取原图 → 类别映射 → 近重复分组 → 按组分层划分（执行计划 0019）。

用法：
    .venv/bin/python data/prepare_dm.py                          # 默认只用 cdr（Cucumber Disease Recognition Dataset）
    .venv/bin/python data/prepare_dm.py --sources cdr,cld        # 加上 Cucurbit Leaf Disease Dataset
    .venv/bin/python data/prepare_dm.py --zip cdr=路径.zip       # 用手动下载好的压缩包（Mendeley 页面「Download All」）
    .venv/bin/python data/prepare_dm.py --license cdr="CC BY 4.0"  # 接口读不到许可时，人工核对页面后填写
    .venv/bin/python data/prepare_dm.py --inspect                # 只下载解压并列出目录与类别映射，不生成数据集

产物（ultralytics 分类数据集格式，ml/data/* 已 gitignore）：
    data/dm_cls/{train,val,test}/{downy_mildew,healthy}/*.jpg   训练用，长边缩到 ≤1024
    data/dm_heldout/other_leaf/*.jpg                             其他叶部病害，只用来查误报，不参与训练
    data/dm_cls/manifest.json                                    来源、许可、压缩包 SHA-256、口径、排除项、各划分数量
    data/dm_cls/index.json                                       每张图的来源、原类别、标签、组号、划分（eval_dm.py 按来源和原类别分报）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = ML_ROOT / "data" / "dm_raw"
OUT_ROOT = ML_ROOT / "data" / "dm_cls"
HELDOUT_ROOT = ML_ROOT / "data" / "dm_heldout"

# sha256 为空表示还没固定版本：首次下载后把脚本打印的值填进来，之后校验不符就停止
SOURCES = {
    "cdr": {
        "name": "Cucumber Disease Recognition Dataset v1",
        "mendeley_id": "y6d3z6f8z9", "version": 1, "doi": "10.17632/y6d3z6f8z9.1",
        "citation": "Sultana N., Shorif S.B., Akter M., Uddin M.S. A dataset for successful recognition of "
                    "cucumber diseases. Data in Brief 49 (2023) 109320.",
        "sha256": None,
    },
    "cld": {
        "name": "Cucurbit Leaf Disease Dataset v1",
        "mendeley_id": "whw368mjvv", "version": 1, "doi": "10.17632/whw368mjvv.1",
        "citation": "Monisha R. Cucurbit Leaf Disease Dataset. Mendeley Data, V1, 2025.",
        "sha256": None,
    },
}
ALLOWED_LICENSES = {"CC BY 4.0", "CC0 1.0"}

LABELS = ("downy_mildew", "healthy")
OTHER = "other_leaf"
IGNORE = "ignore"
# 按目录名映射类别，从最深一级往上找第一个命中的；果实类放在「fresh」之前，避免 Fresh Cucumber 被当成健康叶
CLASS_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"fresh\s*cucumber|belly\s*rot|pythium|fruit", re.I), IGNORE),
    (re.compile(r"downy", re.I), "downy_mildew"),
    (re.compile(r"fresh|healthy", re.I), "healthy"),
    (re.compile(r"anthracnose|bacterial|gummy|stem\s*blight|leaf\s*curl|mosaic|powdery|leaf\s*spot|target\s*spot",
                re.I), OTHER),
]
AUGMENTED = re.compile(r"augment", re.I)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

HASH_GRID = 9          # 9×9 灰度缩略图，每行 8 个相邻差 → 64 位
MAX_HAMMING = 4        # 8 个方向里任一方向距离 ≤ 4 即视为同源
SPLIT_FRACTIONS = {"test": 0.15, "val": 0.15}
MAX_SIDE = 1024
SEED = 42


# ---------- 纯函数（ml/test_prepare_dm.py 覆盖，不依赖 numpy / PIL） ----------

def label_for_parts(parts: list[str] | tuple[str, ...]) -> tuple[str | None, str | None]:
    """路径各级目录名 → (标签, 命中的原类别目录名)；都不命中返回 (None, None)。"""
    for part in reversed(parts):
        for pattern, label in CLASS_RULES:
            if pattern.search(part):
                return label, part
    return None, None


def is_augmented(parts: list[str] | tuple[str, ...]) -> bool:
    return any(AUGMENTED.search(p) for p in parts)


def normalize_license(text: str) -> str:
    """「CC-BY-4.0」「Creative Commons Attribution 4.0 International」、许可链接等写法 → 「CC BY 4.0」。
    认不出的写法原样返回（不在白名单里，脚本会停下来等人确认），宁可多问不可放过 NC / ND。"""
    raw = text.strip()
    if m := re.search(r"creativecommons\.org/licenses/([a-z\-]+)/(\d\.\d)", raw, re.I):
        return f"CC {m.group(1).upper().replace('-', ' ')} {m.group(2)}"
    if re.search(r"creativecommons\.org/publicdomain/zero|\bCC0\b|PUBLIC DOMAIN", raw, re.I):
        return "CC0 1.0"
    t = re.sub(r"[\s_\-]+", " ", raw).upper()
    t = re.sub(r"^CREATIVE COMMONS ATTRIBUTION\b", "CC BY", t)
    for long, short in (("NON COMMERCIAL", "NC"), ("NONCOMMERCIAL", "NC"), ("SHARE ALIKE", "SA"), ("SHAREALIKE", "SA"),
                        ("NO DERIVATIVES", "ND"), ("NODERIVATIVES", "ND"), ("NODERIVS", "ND")):
        t = t.replace(long, short)
    t = re.sub(r" (INTERNATIONAL|GENERIC|PUBLIC LICENSE|LICENSE)\b", "", t).strip()
    return t if re.fullmatch(r"CC BY( NC)?( SA| ND)? \d\.\d", t) else raw


def dihedral(grid: list[list[int]]) -> list[list[list[int]]]:
    """方阵的 8 个方向：旋转 0/90/180/270 度，各自再左右翻转。"""
    out, g = [], grid
    for _ in range(4):
        out.append(g)
        out.append([row[::-1] for row in g])
        g = [list(row) for row in zip(*g[::-1])]  # 顺时针转 90 度
    return out


def dhash(grid: list[list[int]]) -> int:
    """前 HASH_GRID-1 行的水平相邻差 → 64 位整数（左 > 右记 1）。"""
    bits = 0
    for row in grid[:HASH_GRID - 1]:
        for left, right in zip(row, row[1:]):
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def variant_hashes(grid: list[list[int]]) -> list[int]:
    return [dhash(g) for g in dihedral(grid)]


def group_near_duplicates(hashes: list[list[int]], max_dist: int = MAX_HAMMING) -> list[int]:
    """每张图 8 个方向的哈希 → 每张图的组号（并查集，传递合并）。

    用第 0 方向哈希建 8 段 × 8 位的索引：汉明距离 ≤ 7 的两张图至少有一段完全相同，只比较同段候选。"""
    parent = list(range(len(hashes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    assert max_dist < 8, "分段索引只保证汉明距离 ≤ 7 的候选不漏"
    bands: dict[tuple[int, int], list[int]] = {}
    for i, hs in enumerate(hashes):
        for b in range(8):
            bands.setdefault((b, (hs[0] >> (8 * b)) & 0xFF), []).append(i)
    for j, hs in enumerate(hashes):
        for h in hs:
            candidates = {i for b in range(8) for i in bands.get((b, (h >> (8 * b)) & 0xFF), ()) if i < j}
            for i in candidates:
                if (h ^ hashes[i][0]).bit_count() <= max_dist:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[max(ri, rj)] = min(ri, rj)
    return [find(i) for i in range(len(hashes))]


def split_groups(groups: dict[int, str], sizes: dict[int, int], seed: int = SEED,
                 fractions: dict[str, float] = SPLIT_FRACTIONS) -> dict[int, str]:
    """按组分层划分：每个标签内把组打乱，依次填满测试、验证（按张数），其余进训练。返回 组号 → 划分。"""
    rng = random.Random(seed)
    result: dict[int, str] = {}
    for label in sorted(set(groups.values())):
        members = sorted(g for g, lab in groups.items() if lab == label)
        rng.shuffle(members)
        total = sum(sizes[g] for g in members)
        targets = [(split, round(total * frac)) for split, frac in fractions.items()]
        filled = {split: 0 for split, _ in targets}
        for g in members:
            split = next((s for s, need in targets if filled[s] < need), "train")
            result[g] = split
            filled[split] = filled.get(split, 0) + sizes[g]
    return result


# ---------- 下载与读许可 ----------

def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_license(source: dict) -> str | None:
    """从 Mendeley 公开接口读许可；接口或字段变化时返回 None，由人工用 --license 补。"""
    for url in (f"https://data.mendeley.com/public-api/datasets/{source['mendeley_id']}/versions/{source['version']}",
                f"https://data.mendeley.com/public-api/datasets/{source['mendeley_id']}"):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                meta = json.load(resp)
        except Exception as exc:  # noqa: BLE001
            print(f"  读许可失败 {url}：{exc}")
            continue
        found = []

        def walk(node, key=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, k if "licen" in k.lower() else key)
            elif isinstance(node, list):
                for v in node:
                    walk(v, key)
            elif isinstance(node, str) and key:
                found.append(node)

        walk(meta)
        names = [s for s in found if re.search(r"CC|Creative|Public Domain", s, re.I)]
        names.sort(key=lambda s: s.lower().startswith("http"))  # 名称优先于链接
        if names:
            return names[0]
    return None


def ensure_zip(key: str, source: dict, override: Path | None) -> Path:
    zip_path = override or RAW_ROOT / f"{key}.zip"
    if not zip_path.exists():
        url = f"https://data.mendeley.com/public-api/zip/{source['mendeley_id']}/download/{source['version']}"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"下载 {url} …")
        try:
            urllib.request.urlretrieve(url, zip_path)
        except Exception as exc:  # noqa: BLE001
            zip_path.unlink(missing_ok=True)
            raise SystemExit(f"下载失败：{exc}\n  请在 https://data.mendeley.com/datasets/{source['mendeley_id']}/{source['version']} "
                             f"点 Download All，再用 --zip {key}=路径")
    actual = sha256sum(zip_path)
    if source["sha256"] and actual != source["sha256"]:
        raise SystemExit(f"{key} 压缩包 SHA-256 不符：{actual} ≠ {source['sha256']}——文件损坏或来源变化，已停止")
    if not source["sha256"]:
        print(f"  {key} 压缩包 SHA-256 = {actual}（尚未固定版本：确认无误后填进 SOURCES）")
    return zip_path


def extract_all(zip_path: Path, target: Path) -> None:
    """解压，压缩包里套压缩包的继续解，直到没有为止。"""
    if not target.exists():
        print(f"解压 {zip_path.name} …")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target)
    while inner := [p for p in target.rglob("*.zip") if not (p.parent / f"{p.stem}.unzipped").exists()]:
        for p in inner:
            print(f"  解压内层 {p.relative_to(target)}")
            with zipfile.ZipFile(p) as zf:
                zf.extractall(p.parent / p.stem)
            (p.parent / f"{p.stem}.unzipped").touch()
    if any(target.rglob("*.rar")):
        raise SystemExit(f"{target} 里有 .rar，脚本不解 rar：手动解开后重跑")


# ---------- 建索引、分组、写出 ----------

def thumbnail_grid(path: Path) -> tuple[list[list[int]], tuple[int, int]]:
    from PIL import Image

    with Image.open(path) as img:
        size = img.size
        small = img.convert("L").resize((HASH_GRID, HASH_GRID), Image.BILINEAR)
        values = list(small.getdata())
    return [values[r * HASH_GRID:(r + 1) * HASH_GRID] for r in range(HASH_GRID)], size


def index_source(key: str, root: Path) -> tuple[list[dict], dict[str, int]]:
    items, skipped = [], {"augmented": 0, "unmapped": 0, "ignored_class": 0, "unreadable": 0}
    unmapped_dirs: dict[str, int] = {}
    for path in sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()):
        parts = path.relative_to(root).parts[:-1]
        if "__MACOSX" in parts or path.name.startswith("._"):  # macOS 打包的资源分叉文件
            continue
        if is_augmented(parts):
            skipped["augmented"] += 1
            continue
        label, source_class = label_for_parts(parts)
        if label is None:
            skipped["unmapped"] += 1
            unmapped_dirs["/".join(parts)] = unmapped_dirs.get("/".join(parts), 0) + 1
            continue
        if label == IGNORE:
            skipped["ignored_class"] += 1
            continue
        try:
            grid, size = thumbnail_grid(path)
        except Exception:  # noqa: BLE001
            skipped["unreadable"] += 1
            continue
        items.append({"path": path, "source": key, "source_class": source_class, "label": label,
                      "hashes": variant_hashes(grid), "size": size})
    for d, n in sorted(unmapped_dirs.items()):
        print(f"  [{key}] 未映射目录 {d or '（根目录）'}：{n} 张")
    return items, skipped


def save_resized(src: Path, dst: Path) -> None:
    from PIL import Image

    with Image.open(src) as img:
        img = img.convert("RGB")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.BILINEAR)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, quality=92)


def parse_pairs(values: list[str], what: str) -> dict[str, str]:
    out = {}
    for v in values:
        key, sep, rest = v.partition("=")
        if not sep or key not in SOURCES:
            raise SystemExit(f"{what} 写成 来源=值，来源只能是 {sorted(SOURCES)}：{v}")
        out[key] = rest
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="准备黄瓜霜霉病分类数据集（计划 0019）")
    ap.add_argument("--sources", default="cdr", help=f"逗号分隔，可选 {sorted(SOURCES)}")
    ap.add_argument("--zip", action="append", default=[], help="来源=手动下载的压缩包路径")
    ap.add_argument("--license", action="append", default=[], help="来源=人工核对页面后的许可（接口读不到时）")
    ap.add_argument("--accept-license", action="append", default=[],
                    help=f"来源=许可：许可不在 {sorted(ALLOWED_LICENSES)} 时人工确认可用，写入清单")
    ap.add_argument("--inspect", action="store_true", help="只解压并列出目录和类别映射")
    args = ap.parse_args(argv)

    keys = [k.strip() for k in args.sources.split(",") if k.strip()]
    if unknown := [k for k in keys if k not in SOURCES]:
        raise SystemExit(f"未知来源 {unknown}，可选 {sorted(SOURCES)}")
    zips = {k: Path(v) for k, v in parse_pairs(args.zip, "--zip").items()}
    manual = parse_pairs(args.license, "--license")
    accepted = {k: normalize_license(v) for k, v in parse_pairs(args.accept_license, "--accept-license").items()}

    sources_meta, all_items, skipped = {}, [], {}
    for key in keys:
        source = SOURCES[key]
        raw_license = manual.get(key) or fetch_license(source)
        if raw_license is None and args.inspect:
            raw_license = "（未读到）"
        if raw_license is None:
            raise SystemExit(f"{key} 读不到许可：打开 https://data.mendeley.com/datasets/{source['mendeley_id']}/{source['version']} "
                             f"核对后用 --license {key}=\"CC BY 4.0\" 之类重跑")
        license_name = normalize_license(raw_license)
        if not args.inspect and license_name not in ALLOWED_LICENSES and accepted.get(key) != license_name:
            raise SystemExit(f"{key} 的许可是「{raw_license}」，不在 {sorted(ALLOWED_LICENSES)} 里。"
                             f"确认可以用于训练后加 --accept-license {key}=\"{license_name}\"")
        zip_path = ensure_zip(key, source, zips.get(key))
        extract_root = RAW_ROOT / key
        extract_all(zip_path, extract_root)
        print(f"[{key}] 许可 {license_name}（{'人工填写' if key in manual else '接口读取'}）")
        items, skip = index_source(key, extract_root)
        by_class: dict[str, int] = {}
        for it in items:
            by_class[f"{it['label']} ← {it['source_class']}"] = by_class.get(f"{it['label']} ← {it['source_class']}", 0) + 1
        for name, n in sorted(by_class.items()):
            print(f"  [{key}] {name}：{n} 张")
        print(f"  [{key}] 跳过 {skip}")
        sources_meta[key] = {**source, "sha256_actual": sha256sum(zip_path), "license": license_name,
                             "license_raw": raw_license, "license_from": "manual" if key in manual else "api",
                             "license_accepted_manually": key in accepted}
        skipped[key] = skip
        all_items += items
    if args.inspect:
        return

    group_of = group_near_duplicates([it["hashes"] for it in all_items])
    members: dict[int, list[dict]] = {}
    for it, g in zip(all_items, group_of):
        it["group"] = g
        members.setdefault(g, []).append(it)
    conflicts = {g for g, ms in members.items() if len({m["label"] for m in ms}) > 1}
    trainable = {g: ms[0]["label"] for g, ms in members.items() if g not in conflicts and ms[0]["label"] in LABELS}
    split_of = split_groups(trainable, {g: len(members[g]) for g in trainable})

    for root in (OUT_ROOT, HELDOUT_ROOT):
        if root.exists():
            shutil.rmtree(root)
    index, counts = [], {}
    for it in all_items:
        g = it["group"]
        if g in conflicts:
            split = "excluded_conflict"
        elif it["label"] == OTHER:
            split = "heldout_other"
        else:
            split = split_of[g]
        digest = hashlib.sha1(str(it["path"]).encode()).hexdigest()[:12]
        if split == "heldout_other":
            rel = Path(OTHER) / f"{it['source']}-{digest}.jpg"
            save_resized(it["path"], HELDOUT_ROOT / rel)
            rel = Path("..") / HELDOUT_ROOT.name / rel
        elif split in ("train", "val", "test"):
            rel = Path(split) / it["label"] / f"{it['source']}-{digest}.jpg"
            save_resized(it["path"], OUT_ROOT / rel)
        else:
            rel = None
        index.append({"file": str(rel) if rel else None, "original": str(it["path"].relative_to(RAW_ROOT)),
                      "source": it["source"], "source_class": it["source_class"], "label": it["label"],
                      "group": g, "split": split, "size": list(it["size"])})
        bucket = counts.setdefault(split, {})
        bucket[f"{it['source']}/{it['label']}"] = bucket.get(f"{it['source']}/{it['label']}", 0) + 1

    group_sizes = sorted((len(ms) for ms in members.values()), reverse=True)
    manifest = {
        "plan": "0019", "sources": sources_meta, "labels": list(LABELS), "heldout_label": OTHER,
        "class_rules": [[p.pattern, lab] for p, lab in CLASS_RULES],
        "dedup": {"hash": f"dhash {HASH_GRID}x{HASH_GRID} × 8 dihedral", "max_hamming": MAX_HAMMING,
                  "groups": len(members), "multi_image_groups": sum(1 for s in group_sizes if s > 1),
                  "largest_groups": group_sizes[:10], "conflict_groups": len(conflicts)},
        "split_fractions": SPLIT_FRACTIONS, "seed": SEED, "max_side_px": MAX_SIDE,
        "skipped": skipped, "counts": counts,
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_ROOT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    for split in ("train", "val", "test", "heldout_other", "excluded_conflict"):
        print(f"[{split}] {counts.get(split, {})}")
    print(f"近重复：{manifest['dedup']['groups']} 组，多张同组 {manifest['dedup']['multi_image_groups']} 组，"
          f"最大组 {group_sizes[:5]}，标签矛盾 {len(conflicts)} 组")
    print(f"完成：{OUT_ROOT}")


if __name__ == "__main__":
    main()
