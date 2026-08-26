"""合成"农田照片"（Pillow 纯绘制）：healthy 茂密绿 / stress 枯黄斑 / soil 裸土缺苗。

说明：这不是真实照片，而是给占位识别算法(颜色统计)与将来 YOLO
联调用的可控视觉样本——斑块的密度/位置由场景参数决定，可复现。
"""
from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw

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
