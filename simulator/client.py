"""AgriScout 平台 HTTP 客户端：模拟器唯一的世界通道。

纪律（基线 D5）：本目录只允许通过 HTTP 与平台对话，
禁止 import 后端任何内部模块——模拟器存在的意义就是验证协议契约。
"""
from __future__ import annotations

from typing import Any

import httpx


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        # 现场平台通常在局域网；不要把本机 SOCKS/HTTP 代理继承到本地协议请求。
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)

    def close(self) -> None:
        self._client.close()

    # ---------- 底层 ----------
    def _req(self, method: str, path: str, json_body: Any = None,
             expect: tuple[int, ...] = (200,)) -> Any:
        resp = self._client.request(method, path, json=json_body)
        if resp.status_code not in expect:
            raise ApiError(
                f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}"
            )
        if method == "DELETE" or not resp.content:
            return None
        return resp.json()

    def get(self, path: str) -> Any:
        return self._req("GET", path)

    def post(self, path: str, body: Any, expect=(200, 201)) -> Any:
        return self._req("POST", path, json_body=body, expect=expect)

    def patch(self, path: str, body: Any) -> Any:
        return self._req("PATCH", path, json_body=body)

    # ---------- 业务封装 ----------
    def health(self) -> dict:
        return self.get("/api/v1/health")

    def list_fields(self) -> list[dict]:
        return self.get("/api/v1/fields")

    def list_crops(self) -> list[dict]:
        return self.get("/api/v1/crops")

    def list_devices(self) -> list[dict]:
        return self.get("/api/v1/devices")

    def create_planting(self, field_id: int, crop_id: int, sowing_date: str) -> dict:
        return self.post("/api/v1/plantings", {
            "field_id": field_id, "crop_id": crop_id, "sowing_date": sowing_date,
        })

    def list_plantings(self, field_id: int | None = None, status: str | None = None) -> list[dict]:
        qs = []
        if field_id is not None:
            qs.append(f"field_id={field_id}")
        if status:
            qs.append(f"status={status}")
        suffix = ("?" + "&".join(qs)) if qs else ""
        # 该端点返回纯数组（管理页规模，未分页）
        return self.get(f"/api/v1/plantings{suffix}")

    def ingest_patrol(self, package: dict) -> dict:
        return self.post("/api/v1/ingest/patrol", package, expect=(200, 201))

    def get_patrol(self, patrol_id: int) -> dict:
        return self.get(f"/api/v1/patrols/{patrol_id}")

    def get_advices(self, patrol_id: int, limit: int = 500) -> dict:
        return self.get(f"/api/v1/patrols/{patrol_id}/advices?limit={limit}")

    # ---------- 建档助手（存在即复用，幂等）----------
    def ensure_device(self, code: str, name: str, model: str = "SimRover v1") -> dict:
        for d in self.list_devices():
            if d["code"] == code:
                return d
        return self.post("/api/v1/devices", {
            "code": code, "name": name, "type": "rover", "model": model,
        })

    def register_device(self, code: str, name: str, model: str = "SimRover v1") -> dict:
        """按 code 幂等注册模拟设备；只通过平台 HTTP 协议。"""
        return self.post("/api/v1/devices/register", {
            "code": code, "name": name, "type": "rover", "model": model,
        }, expect=(200,))

    def send_heartbeat(self, device_id: int, heartbeat: dict[str, Any]) -> dict:
        """发送设备状态心跳，不在模拟器内推断硬件测量值。"""
        return self.post(f"/api/v1/devices/{device_id}/heartbeat", heartbeat, expect=(200,))

    def report_event(self, device_id: int, event: dict[str, Any]) -> dict:
        """发送设备事件；由 client_event_id 支持网络重试幂等。"""
        return self.post(f"/api/v1/devices/{device_id}/events", event, expect=(201,))

    def report_mission_event(self, mission_id: int, event: dict[str, Any]) -> dict:
        """发送任务事件；平台当前以 Patrol id 作为 mission_id。"""
        return self.post(f"/api/v1/missions/{mission_id}/events", event, expect=(201,))

    def next_task(self, device_id: int) -> dict | None:
        """领取优先级最高的待执行复巡任务，无任务时返回 None。"""
        return self.get(f"/api/v1/devices/{device_id}/tasks/next")

    def report_task_status(
        self, task_id: int, status: str, *, result_note: str | None = None,
    ) -> dict:
        """回报任务状态；实际运动和安全停车由设备端控制器负责。"""
        body: dict[str, Any] = {"status": status}
        if result_note is not None:
            body["result_note"] = result_note
        return self.patch(f"/api/v1/revisit-tasks/{task_id}", body)

    def ensure_field(self, name: str, boundary: dict, area_ha: float | None = None,
                     soil_type: str = "壤土") -> dict:
        for f in self.list_fields():
            if f["name"] == name:
                return f
        return self.post("/api/v1/fields", {
            "name": name, "boundary": boundary, "area_ha": area_ha, "soil_type": soil_type,
        })

    def ensure_crop(self, name: str, variety: str, lifecycle_days: int,
                    stages: list[dict]) -> dict:
        """按名称复用；若生育期表不一致则以模拟器标准为准修正（保证日历推算正确）。"""
        for c in self.list_crops():
            if c["name"] != name:
                continue
            if c.get("lifecycle_days") != lifecycle_days or len(c.get("stages") or []) != len(stages):
                return self.patch(f"/api/v1/crops/{c['id']}", {
                    "variety": variety, "lifecycle_days": lifecycle_days, "stages": stages,
                })
            return c
        return self.post("/api/v1/crops", {
            "name": name, "variety": variety,
            "lifecycle_days": lifecycle_days, "stages": stages,
        })

    def ensure_planting(self, field_id: int, crop_id: int, sowing_date: str) -> dict:
        for p in self.list_plantings(field_id=field_id, status="active"):
            if p["crop_id"] == crop_id and p["sowing_date"] == sowing_date:
                return p
        return self.create_planting(field_id, crop_id, sowing_date)
