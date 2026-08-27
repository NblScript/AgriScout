"""下载离线地图瓦片 → frontend/public/tiles/{z}/{x}/{y}.png。

用法：
    python3 tools/download_tiles.py --lat 39.10 --lng 116.10 --min-z 13 --max-z 18 --radius-m 1200

策略：本地瓦片优先（Leaflet tileerror 时回退在线源），保障比赛现场断网演示。
范围：以演示田为中心的小半径（默认 1.2km）+ 低缩放级全域各 1-4 张，总量 ~200 张 / ~3MB，可入库。
数据源 OpenStreetMap（© OpenStreetMap contributors），少量下载符合使用政策。

网络安全（SSRF 防御）：
- 主机白名单常量 TILE_HOST，唯一允许的下载目标
- 请求前解析 DNS 并断言全部结果为公网地址（阻断内网/环回/链路本地/云元数据）
- 禁用重定向（重定向目标不校验即不放行）
- z/x/y 整数范围断言，无用户可控的 URL 主机/协议
"""
import argparse
import ipaddress
import math
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "frontend" / "public" / "maptiles"
TILE_HOST = "tile.openstreetmap.org"  # 唯一允许的下载主机（白名单）
MAX_Z = 19
UA = "AgriScout-offline-tiles/1.0 (competition demo)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        raise urllib.error.HTTPError(req.full_url, code, "redirects disabled", headers, fp)


_opener = urllib.request.build_opener(_NoRedirect)


def assert_public_host(host: str) -> None:
    """解析 DNS 并断言全部地址为全球公网（阻断内网/环回/元数据端点/DNS rebinding 目标）。"""
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SystemExit(f"安全拦截：{host} 解析到非公网地址 {ip}")


def tile_url(z: int, x: int, y: int) -> str:
    """构造瓦片 URL：整数参数 + 范围断言 + 主机白名单。"""
    assert 0 <= z <= MAX_Z and 0 <= x < 2**z and 0 <= y < 2**z, f"瓦片坐标越界 {z}/{x}/{y}"
    return f"https://{TILE_HOST}/{z}/{x}/{y}.png"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return _opener.open(req, timeout=15).read()


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
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lng", type=float, required=True)
    ap.add_argument("--radius-m", type=float, default=2500,
                    help="覆盖半径（默认 2.5km：z15 下约±7 行瓦片，保证全屏视口含边缘都在缓存内）")
    ap.add_argument("--min-z", type=int, default=13)
    ap.add_argument("--max-z", type=int, default=18)
    args = ap.parse_args()

    assert_public_host(TILE_HOST)
    dlat, dlng = meters_to_deg(args.radius_m, args.lat)
    total = done = skipped = failed = 0
    for z in range(args.min_z, args.max_z + 1):
        x0, y0 = lnglat_to_tile(args.lng - dlng, args.lat + dlat, z)
        x1, y1 = lnglat_to_tile(args.lng + dlng, args.lat - dlat, z)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                total += 1
                target = OUT / str(z) / str(x) / f"{y}.png"
                if target.exists() and target.stat().st_size > 0:
                    skipped += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.write_bytes(fetch(tile_url(z, x, y)))
                    done += 1
                    time.sleep(0.5)  # 礼貌限速：0.1s 曾触发 OSM 反滥用封锁（Access blocked）
                except Exception as e:
                    failed += 1
                    print(f"失败 z{z}/{x}/{y}: {e}")
        print(f"z{z}: 累计 {done + skipped}/{total}")

    size_mb = sum(f.stat().st_size for f in OUT.rglob("*.png")) / 1e6
    print(f"完成：新下 {done}，已有 {skipped}，失败 {failed}；总大小 {size_mb:.1f}MB → {OUT}")


if __name__ == "__main__":
    main()
