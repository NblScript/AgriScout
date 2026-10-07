"""合成"农田照片"（Pillow 纯绘制）：healthy 茂密绿 / stress 枯黄斑 / soil 裸土缺苗；另有大棚黄瓜叶片近景（计划 0017）。

说明：这不是真实照片，而是给占位识别算法(颜色统计)与将来 YOLO
联调用的可控视觉样本——斑块的密度/位置由场景参数决定，可复现。
"""
from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageFilter

SIZE = (160, 120)


def _green_base(rng: random.Random, size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, (32 + rng.randint(-4, 6), 88 + rng.randint(-8, 10), 46))
    draw = ImageDraw.Draw(img)
    w, h = size
    for _ in range(320):
        x, y = rng.randrange(w), rng.randrange(h)
        length = rng.randint(4, 11)
        dx = rng.randint(-2, 2)
        shade = rng.randint(-18, 26)
        color = (34 + shade // 2, 96 + shade, 48 + shade // 3)
        draw.line([(x, y), (x + dx, y - length)], fill=color, width=1)
    return img


def _add_stress_blobs(img: Image.Image, count: int, rng: random.Random) -> None:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for _ in range(count):
        cx, cy = rng.randrange(w), rng.randrange(h)
        rx, ry = rng.randint(5, 16), rng.randint(4, 12)
        brown = (105 + rng.randint(-12, 14), 78 + rng.randint(-10, 10), 42 + rng.randint(-8, 8))
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=brown)


def make_photo_bytes(mode: str, intensity: float, rng: random.Random,
                     size: tuple[int, int] = SIZE) -> bytes:
    """mode: healthy | stress | soil；intensity 0-1 控制 stress 斑块密度。"""
    if mode == "soil":
        img = Image.new("RGB", size, (112, 84, 56))
        draw = ImageDraw.Draw(img)
        w, h = size
        for _ in range(26):  # 零星杂草
            x, y = rng.randrange(w), rng.randrange(h)
            draw.point((x, y), fill=(60 + rng.randint(0, 30), 110 + rng.randint(0, 40), 55))
    else:
        img = _green_base(rng, size)
        if mode == "stress":
            _add_stress_blobs(img, max(1, int(intensity * 16)), rng)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


# 叶片近景的病斑颜色：占位分析器把黄褐色像素记为「胁迫」，风险分约等于 2.5 × 病斑像素占比。
# 真实的霜霉病叶背是灰紫色霉层，这里只为让占位分析器给出可控的分数，不追求像。
LESION_COLOR = (176, 148, 52)


def make_leaf_photo_bytes(lesion_fraction: float, rng: random.Random, *, side: str = "under",
                          blurred: bool = False, size: tuple[int, int] = SIZE) -> bytes:
    """黄瓜叶片近景：绿底加叶脉，多边形病斑铺到 lesion_fraction（0–0.6）为止；blurred 模拟虚焦（拍摄不合格）。"""
    base = (70, 158, 78) if side == "under" else (46, 150, 62)  # 叶背颜色稍浅
    img = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(img)
    w, h = size
    for i in range(1, 7):  # 主脉与侧脉
        x = i * w // 7
        draw.line([(w // 2, h), (x, 0)], fill=(base[0] + 30, base[1] + 34, base[2] + 22), width=1)
    mask = Image.new("L", size, 0)
    mask_draw = ImageDraw.Draw(mask)
    target = max(0.0, min(lesion_fraction, 0.6)) * w * h
    for _ in range(400):  # 叶脉限制下的多角形病斑，铺够面积即停
        if mask.histogram()[255] >= target:
            break
        cx, cy = rng.randrange(w), rng.randrange(h)
        r = rng.randint(5, 12)
        poly = [(cx + rng.randint(-r, r), cy + rng.randint(-r, r)) for _ in range(5)]
        color = tuple(c + rng.randint(-8, 8) for c in LESION_COLOR)
        draw.polygon(poly, fill=color)
        mask_draw.polygon(poly, fill=255)
    if blurred:
        img = img.filter(ImageFilter.GaussianBlur(3))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
