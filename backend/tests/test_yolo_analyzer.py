"""M-AI YOLO 分析器测试：检测映射逻辑（注入 fake 模型，无需 torch）。"""
import base64
from datetime import datetime

from conftest import png_b64

from app.services.analysis.base import CaptureContext
from app.services.analysis.yolo_detector import YoloAnalyzer


def png_bytes(rgb: tuple[int, int, int]) -> bytes:
    return base64.b64decode(png_b64(rgb))


GREEN = png_bytes((40, 160, 60))
BROWN = png_bytes((120, 85, 50))

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


# ---------------------------------------------------------------- 条锈病图块分类（计划 0010）

from app.services.analysis.disease_classifier import TileProb, tile_boxes  # noqa: E402


def _tiles(probs: list[float]) -> list[TileProb]:
    boxes = tile_boxes(640, 480)
    assert len(boxes) == len(probs)
    return [TileProb((x / 640, y / 480, w / 640, h / 480), p) for (x, y, w, h), p in zip(boxes, probs)]


def test_tile_grid_matches_training_geometry():
    """短边 3 格、正方形、贴边补齐：640×480 → 4×3 共 12 块、边长 160；竖拍同理。"""
    boxes = tile_boxes(640, 480)
    assert len(boxes) == 12 and {w for _, _, w, _ in boxes} == {160}
    assert max(x + w for x, _, w, _ in boxes) == 640 and max(y + h for _, y, _, h in boxes) == 480
    assert len(tile_boxes(480, 640)) == 12
    uneven = tile_boxes(700, 480)  # 700 不是 160 的整数倍：最后一列贴右边
    assert max(x + w for x, _, w, _ in uneven) == 700


def test_rust_tiles_give_model_detection_and_risk():
    analyzer = YoloAnalyzer(model_path=None, disease_model_path="/models/rust-cls-v1.pt")
    probs = [0.02] * 12
    probs[5], probs[6] = 0.93, 0.61
    result = analyzer.build_result(GREEN, CTX, [], _tiles(probs))
    rust = [d for d in result.disease_detections if d["type"] == "stripe_rust"]
    assert len(rust) == 1
    assert rust[0]["confidence"] == 0.93 and rust[0]["area_ratio"] == round(2 / 12, 3)
    assert len(rust[0]["boxes"]) == 2 and all(0 <= v <= 1 for box in rust[0]["boxes"] for v in box)
    assert result.risk_score == 0.93
    assert result.detail["risk_source"] == "disease_model" and result.detail["disease_model"] == "rust-cls-v1"


def test_healthy_tiles_keep_risk_low_even_if_colour_looks_stressed():
    """枯黄色图但模型判为健康：保留颜色胁迫提示（非病害），风险分由模型给出，不被颜色抬高。"""
    analyzer = YoloAnalyzer(model_path=None, disease_model_path="/models/rust-cls-v1.pt")
    result = analyzer.build_result(BROWN, CTX, [], _tiles([0.08] * 12))
    types = [d["type"] for d in result.disease_detections]
    assert types == ["suspected_stress"]
    assert result.risk_score == 0.08
    assert result.detail["rust_tiles"] == 0


def test_without_ear_model_vigor_matches_colour_analyzer():
    from app.services.analysis import PlaceholderColorAnalyzer

    analyzer = YoloAnalyzer(model_path=None, disease_model_path="/models/rust-cls-v1.pt")
    assert analyzer.version == "color+rust-cls-v1"
    assert analyzer._detect(GREEN) == []  # 无麦穗模型不加载 YOLO
    result = analyzer.build_result(GREEN, CTX, [], _tiles([0.1] * 12))
    assert result.vigor_level == PlaceholderColorAnalyzer().analyze(GREEN, CTX).vigor_level


def test_version_and_config_combinations(monkeypatch):
    from app.core.config import get_settings
    from app.services.analysis import _yolo_singleton, get_analyzer

    both = YoloAnalyzer(model_path="./models/wheat-yolo-v1.pt", disease_model_path="./models/rust-cls-v1.pt")
    assert both.version == "yolo-wheat-yolo-v1+rust-cls-v1"
    try:
        YoloAnalyzer(model_path=None)
        raise AssertionError("两个模型都没配应当报错")
    except ValueError as e:
        assert "至少需要" in str(e)

    settings = get_settings()
    monkeypatch.setattr(settings, "analyzer_backend", "yolo")
    monkeypatch.setattr(settings, "yolo_model_path", "")
    monkeypatch.setattr(settings, "disease_model_path", "./models/rust-cls-v1.pt")
    _yolo_singleton.cache_clear()
    try:
        assert get_analyzer().version == "color+rust-cls-v1"
    finally:
        _yolo_singleton.cache_clear()


def test_missing_disease_model_gives_clear_error():
    analyzer = YoloAnalyzer(model_path=None, disease_model_path="/nonexistent/rust-cls-v1.pt")
    try:
        analyzer.analyze(GREEN, CTX)
        raise AssertionError("应当抛出 RuntimeError")
    except RuntimeError as e:
        assert "病害模型文件不存在" in str(e)
