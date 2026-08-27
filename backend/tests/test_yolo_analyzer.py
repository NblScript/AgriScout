"""M-AI YOLO 分析器测试：检测映射逻辑（注入 fake 模型，无需 torch）。"""
import base64
import io

from PIL import Image

from app.services.analysis.base import CaptureContext
from app.services.analysis.yolo_detector import YoloAnalyzer
from datetime import datetime

BASE = "/api/v1"


def _png_bytes(rgb: tuple[int, int, int], size: int = 64) -> bytes:
    img = Image.new("RGB", (size, size), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


GREEN = _png_bytes((40, 160, 60))
BROWN = _png_bytes((120, 85, 50))

CTX = CaptureContext(captured_at=datetime(2026, 9, 20, 8, 0, 0), lng=10.0, lat=10.0)


def _analyzer_with(detections: list[dict]) -> YoloAnalyzer:
    """绕过模型加载：直接注入 build_result 所需的检测输出。"""
    analyzer = YoloAnalyzer(model_path="/nonexistent/model.pt")
    analyzer._detect = lambda image: detections  # type: ignore[method-assign]
    return analyzer


def test_ear_count_boosts_vigor_on_green_image():
    """绿色背景 + 麦穗密集 → 长势高于纯颜色统计。"""
    analyzer = _analyzer_with([
        {"bbox": [0.1 * i, 0.2, 0.08, 0.08], "conf": 0.9} for i in range(40)
    ])
    result = analyzer.build_result(GREEN, CTX, analyzer._detect(GREEN))
    assert result.vigor_level == 5
    assert result.detail["ear_count"] == 40
    assert result.detail["density_score"] == 1.0
    assert result.detail["avg_conf"] == 0.9
    assert 0 < result.ndvi <= 1


def test_no_detections_falls_back_to_color_signal():
    """零检出（未抽穗/漏检）→ 长势由绿色覆盖率主导。"""
    analyzer = _analyzer_with([])
    result = analyzer.build_result(GREEN, CTX, [])
    # 纯绿图 green_ratio≈0.9（缩样边缘混色）→ vigor_index≈0.36 → 长势 4
    assert result.vigor_level == 4
    assert result.detail["ear_count"] == 0
    assert result.detail["avg_conf"] is None


def test_stress_color_still_triggers_disease_fallback():
    """枯黄胁迫色保持与占位版一致的 suspected_stress 检出（规则引擎保底依赖）。"""
    analyzer = _analyzer_with([])
    result = analyzer.build_result(BROWN, CTX, [])
    assert result.disease_detections is not None
    assert result.disease_detections[0]["type"] == "suspected_stress"
    assert result.risk_score > 0.3


def test_growth_stage_calendar_still_works():
    """日历法生育期语义与占位版一致。"""
    from datetime import date

    ctx = CaptureContext(
        captured_at=datetime(2026, 9, 20, 8, 0, 0),
        lng=10.0, lat=10.0,
        sowing_date=date(2026, 8, 1),
        crop_stages=[{"name": "出苗期", "days": 15}, {"name": "分蘖期", "days": 30}],
    )
    analyzer = _analyzer_with([])
    result = analyzer.build_result(GREEN, ctx, [])
    assert result.growth_stage["name"] == "分蘖期"
    assert result.growth_stage["day_after_sowing"] == 50


def test_missing_model_file_gives_clear_error():
    """模型文件缺失时懒加载抛出可读错误（而非 ImportError 堆栈）。"""
    analyzer = YoloAnalyzer(model_path="/nonexistent/model.pt")
    try:
        analyzer.analyze(GREEN, CTX)
        raise AssertionError("应当抛出 RuntimeError")
    except RuntimeError as e:
        assert "模型文件不存在" in str(e)


def test_dispatch_defaults_to_placeholder(client):
    """默认 backend=placeholder：上传巡检后 analyzer_version 不变（31 项既有测试零回归）。"""
    from app.services.analysis import get_analyzer

    assert get_analyzer().version == "placeholder-color-v0"


def test_version_encodes_model_name():
    """analyzer_version 带模型文件名，历史可溯源。"""
    assert YoloAnalyzer(model_path="./models/wheat-yolo-v1.pt").version == "yolo-wheat-yolo-v1"
