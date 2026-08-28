"""下载高德离线瓦片 → frontend/public/gdmaptiles/{z}/{x}/{y}.png。

用法：
    python3 tools/download_tiles.py --lat 39.1003 --lng 116.1003 [--radius-m 2500]

数据源：高德矢量路网图（style=8）。注意高德为 GCJ-02 坐标系——下载时按 GCJ-02
计算瓦片号，前端 Leaflet 侧 WGS84 坐标叠加会有固有的百米级偏移，属可接受误差
（演示以轨迹/点位相对位置为主）。境内访问稳定，无 API key、无封锁页问题。

历史注记：前 OSM 方案因反滥用封锁（批量下载触发 IP 封禁）+ 浏览器缓存毒化废弃；
CARTO 政策收紧（无 key 返回占位图）废弃。天地图需注册 key，暂不采用。

安全（SSRF 防御）：上游主机白名单常量；z/x/y 整数范围断言；请求前 DNS 解析
断言全公网地址；禁用重定向。
"""
import argparse
import ipaddress
import json
import math
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "frontend" / "public" / "gdmaptiles"
TILE_HOST = "webrd0{sub}.is.autonavi.com"  # 高德瓦片子域 1-4 轮询
MAX_Z = 18
UA = "Mozilla/5.0 (X11; Linux x86_64) AgriScout-offline/2.0"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        raise urllib.error.HTTPError(req.full_url, code, "redirects disabled", headers, fp)


_opener = urllib.request.build_opener(_NoRedirect)


def assert_public_host(host: str) -> None:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SystemExit(f"安全拦截：{host} 解析到非公网地址 {ip}")


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02（火星坐标）标准换算。"""
    a = 6378245.0
    ee = 0.00669342162296594323
    if 72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271:
        dlat = _transform_lat(lng - 105.0, lat - 35.0)
        dlng = _transform_lng(lng - 105.0, lat - 35.0)
        radlat = lat / 180.0 * math.pi
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
        return lng + dlng, lat + dlat
    return lng, lat


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def lnglat_to_tile(lng: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def meters_to_deg(radius_m: float, lat: float) -> tuple[float, float]:
    return radius_m / 111320.0, radius_m / (111320.0 * math.cos(math.radians(lat)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True, help="WGS-84 纬度（演示田中心）")
    ap.add_argument("--lng", type=float, required=True, help="WGS-84 经度")
    ap.add_argument("--radius-m", type=float, default=2500)
    ap.add_argument("--min-z", type=int, default=13)
    ap.add_argument("--max-z", type=int, default=18)
    args = ap.parse_args()

    for sub in (1, 2, 3, 4):
        assert_public_host(TILE_HOST.format(sub=sub))

    gcj_lng, gcj_lat = wgs84_to_gcj02(args.lng, args.lat)
    print(f"WGS84 ({args.lng}, {args.lat}) → GCJ02 ({gcj_lng:.6f}, {gcj_lat:.6f})")
    dlat, dlng = meters_to_deg(args.radius_m, args.lat)

    total = done = skipped = failed = 0
    for z in range(args.min_z, args.max_z + 1):
        x0, y0 = lnglat_to_tile(gcj_lng - dlng, gcj_lat + dlat, z)
        x1, y1 = lnglat_to_tile(gcj_lng + dlng, gcj_lat - dlat, z)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                total += 1
                target = OUT / str(z) / str(x) / f"{y}.png"
                if target.exists() and target.stat().st_size > 1000:  # <1KB 多为占位图
                    skipped += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                sub = (x + y) % 4 + 1
                url = f"https://{TILE_HOST.format(sub=sub)}/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&scale=1&style=8"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": UA})
                    data = _opener.open(req, timeout=15).read()
                    if len(data) < 1000:
                        raise ValueError(f"响应 {len(data)}B 疑似占位图")
                    target.write_bytes(data)
                    done += 1
                    time.sleep(0.3)  # 礼貌限速
                except Exception as e:
                    failed += 1
                    print(f"失败 z{z}/{x}/{y}: {e}")
        print(f"z{z}: 累计 {done + skipped}/{total}")

    meta = {"source": "amap-gcj02", "center_wgs84": [args.lng, args.lat],
            "center_gcj02": [round(gcj_lng, 6), round(gcj_lat, 6)], "radius_m": args.radius_m}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    size_mb = sum(f.stat().st_size for f in OUT.rglob("*.png")) / 1e6
    print(f"完成：新下 {done}，已有 {skipped}，失败 {failed}；总 {size_mb:.1f}MB → {OUT}")


if __name__ == "__main__":
    main()
