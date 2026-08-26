"""M3 分析管线测试：上传→后台分析→结果查询全链路。

TestClient 的 BackgroundTasks 随请求周期同步执行，
因此 post 返回后即可断言分析已完成。
"""
import base64
import io

from PIL import Image

BASE = "/api/v1"


def _png_b64(rgb: tuple[int, int, int], size: int = 24) -> str:
    """生成纯色 PNG 的 base64（测试专用"合成农田照片"）。"""
    img = Image.new("RGB", (size, size), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


GREEN = _png_b64((40, 160, 60))     # 茂密植被 → vigor 高
BROWN = _png_b64((120, 85, 50))     # 枯黄/裸土 → vigor 低 + 胁迫检出
DARK = _png_b64((10, 10, 12))       # 过暗 → low_light 标记


def _setup(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={
            "name": "分析测试田",
            "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
        },
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-a01", "name": "分析测试车", "type": "rover"})
    # 登记冬小麦 + 生育期表，验证日历法推生育期
    crop_id = client.post(
        f"{BASE}/crops",
        json={
            "name": "冬小麦",
            "lifecycle_days": 60,
            "stages": [
                {"name": "出苗期", "days": 15},
                {"name": "分蘖期", "days": 30},
                {"name": "拔节期", "days": 15},
            ],
        },
    ).json()["id"]
    planting_id = client.post(
        f"{BASE}/plantings",
        json={"field_id": field_id, "crop_id": crop_id, "sowing_date": "2026-08-01"},
    ).json()["id"]
    return field_id, planting_id


def _package(field_id, planting_id, photo_by_seq: dict[int, str]):
    return {
        "patrol": {
            "field_id": field_id,
            "device": "sim-a01",
            "started_at": "2026-08-26T08:00:00+00:00",
            "ended_at": "2026-08-26T09:00:00+00:00",
        },
        "capture_points": [
            {
                "seq": seq,
                "distance_m": seq * 0.5,
                "lng": 10.001 + seq * 0.001,
                "lat": 10.001,
                "captured_at": f"2026-08-26T08:{seq:02d}:00+00:00",
                "photo": photo_by_seq.get(seq),
            }
            for seq in range(4)
        ],
    }


def test_full_analysis_pipeline(client, media_dir):
    field_id, planting_id = _setup(client)
    # 绿图 / 无照片 / 棕图 / 暗图 四种情形一次覆盖
    pkg = _package(field_id, planting_id, {0: GREEN, 2: BROWN, 3: DARK})
    resp = client.post(f"{BASE}/ingest/patrol", json=pkg)
    assert resp.status_code == 201
    patrol_id = resp.json()["patrol_id"]

    detail = client.get(f"{BASE}/patrols/{patrol_id}").json()
    assert detail["analysis_status"] == "done"
    assert detail["notes"].startswith("analyzed=3 skipped_no_photo=1")

    points = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"]

    # 绿色茂密点：vigor=5、ndvi 为正、无胁迫检出、日历推得分蘖期(第26天)
    green_analysis = points[0]["analysis"]
    assert green_analysis is not None
    assert green_analysis["vigor_level"] == 5
    assert green_analysis["ndvi"] > 0
    assert green_analysis["disease_detections"] is None
    assert green_analysis["risk_score"] < 0.1
    stage = green_analysis["growth_stage"]
    assert stage["name"] == "分蘖期" and stage["source"] == "calendar"
    assert stage["day_after_sowing"] == 25
    assert green_analysis["detail"]["ndvi_is_proxy"] is True
    assert green_analysis["analyzer_version"] == "placeholder-color-v0"

    # 棕色枯黄点：vigor=1、胁迫检出、风险高；日历法同样推得分蘖期
    brown_analysis = points[2]["analysis"]
    assert brown_analysis["vigor_level"] == 1
    assert brown_analysis["disease_detections"][0]["type"] == "suspected_stress"
    assert brown_analysis["risk_score"] >= 0.5
    assert brown_analysis["growth_stage"]["name"] == "分蘖期"
    assert brown_analysis["growth_stage"]["day_after_sowing"] == 25

    # 暗光点：low_light 标记
    dark_analysis = points[3]["analysis"]
    assert dark_analysis["detail"]["low_light"] is True

    # 无照片点：analysis 为 null
    assert points[1]["analysis"] is None

    # 汇总端点（棕图与暗图均无绿色 → vigor 1 共 2 个点）
    summary = client.get(f"{BASE}/patrols/{patrol_id}/analysis-summary").json()
    assert summary["analyzed_points"] == 3 and summary["total_points"] == 4
    assert summary["vigor_distribution"]["5"] == 1
    assert summary["vigor_distribution"]["1"] == 2
    assert summary["stress_flagged_points"] == 1
    assert summary["stage_histogram"] == {"分蘖期": 3}
    assert summary["avg_ndvi"] is not None and summary["analyzer_version"] == "placeholder-color-v0"


def test_reanalyze_is_idempotent(client, media_dir):
    field_id, planting_id = _setup(client)
    resp = client.post(
        f"{BASE}/ingest/patrol", json=_package(field_id, planting_id, {0: GREEN}),
    )
    patrol_id = resp.json()["patrol_id"]
    before = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"][0]["analysis"]

    re_resp = client.post(f"{BASE}/patrols/{patrol_id}/analyze")
    assert re_resp.status_code == 202
    assert re_resp.json()["status"] == "scheduled"

    after = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"][0]["analysis"]
    assert after["vigor_level"] == before["vigor_level"] == 5
    # 幂等：重分析不产生重复行
    summary = client.get(f"{BASE}/patrols/{patrol_id}/analysis-summary").json()
    assert summary["analyzed_points"] == 1


def test_unreadable_photo_skipped_not_error(client, media_dir):
    field_id, _ = _setup(client)
    pkg = _package(field_id, None, {})
    pkg["capture_points"][0]["photo"] = "/media/not-exists.jpg"  # 引用本地不存在文件
    resp = client.post(f"{BASE}/ingest/patrol", json=pkg)
    assert resp.status_code == 201
    detail = client.get(f"{BASE}/patrols/{resp.json()['patrol_id']}").json()
    # 4 个点全部无法取图（引用缺失/无照片），跳过但不报错，状态仍为 done
    assert detail["analysis_status"] == "done"
    assert "analyzed=0 skipped_no_photo=4" in detail["notes"]


def test_calendar_stage_before_sowing_is_none(client, media_dir):
    field_id, _ = _setup(client)
    pkg = _package(field_id, None, {0: GREEN})
    pkg["capture_points"][0]["captured_at"] = "2026-07-01T08:00:00+00:00"
    resp = client.post(f"{BASE}/ingest/patrol", json=pkg)
    analysis = (
        client.get(f"{BASE}/capture-points?patrol_id={resp.json()['patrol_id']}")
        .json()["items"][0]["analysis"]
    )
    assert analysis is not None
    assert analysis["growth_stage"] is None  # 早于播种日期 → 无法推算
