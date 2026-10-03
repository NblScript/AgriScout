"""计划 0016 阶段 A：平台侧图像质量 iq-rule-v1。

合成图与期望值和 rover/test_acquire.py 完全相同（两边各写一份，红线 6），
两边都断言同一组期望值，从而把车端与平台的公式锁成一致。
"""
import base64
import io
import math

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.services.analysis.image_quality import METHOD, assess_image_quality

BASE = "/api/v1"


# ---- 与 rover/test_acquire.py 一致的合成图（改这里必须同步改那边）----


def _checkerboard() -> Image.Image:
    image = Image.new("L", (320, 240), 60)
    draw = ImageDraw.Draw(image)
    for y in range(0, 240, 8):
        for x in range(0, 320, 8):
            if (x // 8 + y // 8) % 2:
                draw.rectangle([x, y, x + 7, y + 7], fill=200)
    return image


def _synthetic() -> dict[str, Image.Image]:
    overexposed = Image.new("L", (320, 240), 255)
    overexposed.paste(128, (107, 80, 213, 160))
    backlit = Image.new("L", (320, 240), 40)
    backlit.paste(250, (0, 0, 320, 80))
    return {
        "sharp": _checkerboard(),
        "blurry": _checkerboard().filter(ImageFilter.GaussianBlur(4)),
        "overexposed": overexposed,
        "dark": Image.new("L", (320, 240), 3),
        "backlit": backlit,
    }


EXPECTED = {
    "sharp": dict(sharpness=6977.336, mean_luma=0.5098, clip_high=0.0, clip_low=0.0, backlit=False, reasons=[]),
    "blurry": dict(sharpness=4.498, mean_luma=0.5098, clip_high=0.0, clip_low=0.0, backlit=False, reasons=["blurry"]),
    "overexposed": dict(
        sharpness=157.701, mean_luma=0.945, clip_high=0.8896, clip_low=0.0, backlit=False, reasons=["overexposed"],
    ),
    "dark": dict(
        sharpness=0.0, mean_luma=0.0118, clip_high=0.0, clip_low=1.0, backlit=False,
        reasons=["blurry", "underexposed"],
    ),
    "backlit": dict(
        sharpness=136.609, mean_luma=0.4314, clip_high=0.3333, clip_low=0.0, backlit=True,
        reasons=["overexposed", "backlit"],
    ),
}


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_synthetic_images_match_shared_expectations(name):
    result = assess_image_quality(_png(_synthetic()[name]))
    expected = EXPECTED[name]
    assert result["method"] == METHOD
    # 容差：sharpness 相对 1%，其余 1e-3（计划 0016 A7）
    assert math.isclose(result["sharpness"], expected["sharpness"], rel_tol=0.01, abs_tol=0.01)
    for key in ("mean_luma", "clip_high", "clip_low"):
        assert result[key] == pytest.approx(expected[key], abs=1e-3), key
    assert result["backlit"] is expected["backlit"]
    assert result["reasons"] == expected["reasons"]
    assert result["ok"] is (not expected["reasons"])


def test_large_image_is_downscaled_and_small_image_kept():
    big = _checkerboard().resize((1280, 960), Image.Resampling.NEAREST)  # 32px 格子缩回 8px
    assert assess_image_quality(_png(big))["ok"] is True
    tiny = Image.new("L", (2, 2), 128)
    assert assess_image_quality(_png(tiny))["reasons"] == ["blurry"]


def test_exif_orientation_is_applied():
    # 上下颠倒存储 + EXIF 方向 3：旋正后亮区才在上方，才会判逆光
    upside_down = _synthetic()["backlit"].rotate(180)
    exif = Image.Exif()
    exif[0x0112] = 3
    buffer = io.BytesIO()
    upside_down.convert("RGB").save(buffer, format="JPEG", quality=95, exif=exif.tobytes())
    assert assess_image_quality(buffer.getvalue())["backlit"] is True


def test_undecodable_bytes_raise_oserror():
    with pytest.raises(OSError):
        assess_image_quality(b"not an image")


def test_every_analyzed_point_gets_image_quality(client, media_dir):
    field_id = client.post(f"{BASE}/fields", json={
        "name": "质量测试田",
        "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
    }).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-iq", "name": "质量测试车", "type": "rover"})
    photos = {0: _png(_synthetic()["sharp"]), 1: _png(_synthetic()["blurry"])}
    package = {
        "patrol": {
            "field_id": field_id, "device": "sim-iq",
            "started_at": "2026-10-03T08:00:00+00:00", "ended_at": "2026-10-03T08:10:00+00:00",
        },
        "capture_points": [
            {
                "seq": seq, "distance_m": seq * 0.5, "lng": 10.5, "lat": 10.5,
                "captured_at": f"2026-10-03T08:0{seq}:00+00:00",
                "photo": base64.b64encode(photos[seq]).decode() if seq in photos else None,
            }
            for seq in range(3)
        ],
    }
    resp = client.post(f"{BASE}/ingest/patrol", json=package)
    assert resp.status_code == 201
    points = client.get(f"{BASE}/capture-points?patrol_id={resp.json()['patrol_id']}").json()["items"]
    sharp, blurry, no_photo = (p["analysis"] for p in points)
    assert sharp["detail"]["image_quality"]["ok"] is True
    assert sharp["detail"]["image_quality"]["method"] == METHOD
    assert blurry["detail"]["image_quality"]["reasons"] == ["blurry"]
    # analyzer_version 不因质量判断而改变
    assert sharp["analyzer_version"] == "placeholder-color-v0"
    assert no_photo is None
