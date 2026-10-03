"""棚内温湿度记录仪 CSV → 平台环境读数（计划 0015）。

记录仪通常只能导出 CSV：列名各家不同、时间多半是不带时区的当地时间。这里按参数指定列名和时区读入，
分批调用 ``POST /api/v1/fields/{field_id}/env-readings``（每批最多 5000 条），只走 HTTP（红线 6）。
平台按「传感器 + 时刻」去重，同一个文件重复上传是安全的。

用法：
    python env_upload.py --api http://<后端IP>:8000 --field-id 3 --csv th-01.csv --sensor-key th-01 \\
        --time-col 时间 --temp-col 温度 --rh-col 湿度 --tz +08:00
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

try:
    from .run import ApiClient, ApiError
except ImportError:  # 在 rover/ 目录下直接运行 python env_upload.py
    from run import ApiClient, ApiError  # type: ignore[no-redef]

MAX_BATCH = 5000  # 与平台单次上报上限一致
_TZ_PATTERN = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


@dataclass(frozen=True)
class Columns:
    time: str = "time"
    temp: str = "temp_c"
    humidity: str = "humidity_pct"
    leaf_wetness: str | None = None


def parse_tz(text: str) -> tzinfo:
    """``+08:00`` / ``+0800`` / ``UTC`` → 时区；记录仪导出的不带时区时间按它解释。"""
    if text.upper() in {"UTC", "Z"}:
        return timezone.utc
    match = _TZ_PATTERN.match(text)
    if not match:
        raise ValueError(f"时区写成 +08:00 或 UTC，收到 {text!r}")
    sign, hours, minutes = match.groups()
    offset = timedelta(hours=int(hours), minutes=int(minutes))
    return timezone(offset if sign == "+" else -offset)


def _parse_time(value: str, tz: tzinfo, time_format: str | None) -> datetime:
    text = value.strip()
    parsed = datetime.strptime(text, time_format) if time_format else datetime.fromisoformat(text.replace("/", "-"))
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value.strip().rstrip("%"))


def read_csv(
    path: str | Path, *, columns: Columns = Columns(), tz: tzinfo = timezone(timedelta(hours=8)),
    time_format: str | None = None, encoding: str = "utf-8-sig", delimiter: str = ",",
) -> tuple[list[dict[str, Any]], list[str]]:
    """返回 (读数, 错误)。坏行记下行号跳过，不中断整个文件；时间统一转成带时区的 ISO 字符串。"""
    readings: list[dict[str, Any]] = []
    errors: list[str] = []
    with Path(path).open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        needed = [columns.time, columns.temp, columns.humidity] + ([columns.leaf_wetness] if columns.leaf_wetness else [])
        missing = [name for name in needed if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV 缺少列 {missing}，现有列 {reader.fieldnames}")
        for line_no, row in enumerate(reader, start=2):
            try:
                temp, humidity = _number(row[columns.temp]), _number(row[columns.humidity])
                if temp is None or humidity is None:
                    raise ValueError("温度或湿度为空")
                reading: dict[str, Any] = {
                    "observed_at": _parse_time(row[columns.time], tz, time_format).isoformat(),
                    "temp_c": temp, "humidity_pct": humidity,
                }
                if columns.leaf_wetness:
                    wetness = _number(row[columns.leaf_wetness])
                    if wetness is not None:
                        reading["leaf_wetness"] = wetness
                readings.append(reading)
            except (ValueError, TypeError) as exc:
                errors.append(f"第 {line_no} 行：{exc}")
    return readings, errors


def batches(items: Sequence[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    if not 1 <= size <= MAX_BATCH:
        raise ValueError(f"每批条数须在 1–{MAX_BATCH} 之间")
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


def upload(
    client: Any, field_id: int, sensor_key: str, readings: Sequence[dict[str, Any]], *,
    device: str | None = None, source: str = "import", batch_size: int = 1000,
) -> tuple[int, int]:
    """分批上传，返回 (新增, 跳过) 合计。某一批失败时抛出 ApiError，已成功的批次不受影响（重传会被平台跳过）。"""
    inserted = skipped = 0
    for batch in batches(readings, batch_size):
        body: dict[str, Any] = {"sensor_key": sensor_key, "source": source, "readings": batch}
        if device:
            body["device"] = device
        result = client.post(f"/api/v1/fields/{field_id}/env-readings", body, expect=(200,))
        inserted += result["inserted"]
        skipped += result["skipped"]
    return inserted, skipped


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="温湿度记录仪 CSV 上传到 AgriScout")
    parser.add_argument("--api", default="http://localhost:8000", help="后端地址")
    parser.add_argument("--field-id", type=int, required=True, help="大棚地块 id")
    parser.add_argument("--csv", required=True, help="记录仪导出的 CSV 文件")
    parser.add_argument("--sensor-key", required=True, help="记录仪编号或安装位置（字母数字开头，最长 40）")
    parser.add_argument("--device", default=None, help="已在平台登记的设备 code（可选）")
    parser.add_argument("--source", choices=("sensor", "import", "manual"), default="import")
    parser.add_argument("--time-col", default="time", help="时间列名")
    parser.add_argument("--temp-col", default="temp_c", help="温度列名（℃）")
    parser.add_argument("--rh-col", default="humidity_pct", help="相对湿度列名（%%）")
    parser.add_argument("--wetness-col", default=None, help="叶面湿度列名（0–1，可选）")
    parser.add_argument("--time-format", default=None, help="时间格式（strptime），默认按 ISO 解析")
    parser.add_argument("--tz", default="+08:00", help="不带时区的时间按这个时区解释（默认东八区）")
    parser.add_argument("--encoding", default="utf-8-sig", help="文件编码；国产记录仪导出常见 gbk")
    parser.add_argument("--delimiter", default=",", help="分隔符")
    parser.add_argument("--batch-size", type=int, default=1000, help=f"每批条数（≤{MAX_BATCH}）")
    parser.add_argument("--skip-bad", action="store_true", help="有坏行时跳过坏行继续上传（默认整份文件不上传）")
    parser.add_argument("--username", default=os.environ.get("AGRISCOUT_USERNAME"), help="平台账号（操作员及以上）")
    parser.add_argument("--password", default=os.environ.get("AGRISCOUT_PASSWORD"), help="口令（建议用环境变量）")
    parser.add_argument("--token", default=os.environ.get("AGRISCOUT_TOKEN"), help="已签发的访问令牌")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, client_factory=ApiClient) -> int:
    args = parse_args(argv)
    try:
        columns = Columns(args.time_col, args.temp_col, args.rh_col, args.wetness_col)
        readings, errors = read_csv(args.csv, columns=columns, tz=parse_tz(args.tz), time_format=args.time_format,
                                    encoding=args.encoding, delimiter=args.delimiter)
        list(batches([], args.batch_size))  # 提前校验批大小
    except (OSError, ValueError) as exc:
        print(f"[错误] {exc}")
        return 2
    for error in errors[:10]:
        print(f"[坏行] {error}")
    if errors and not args.skip_bad:
        print(f"[错误] 共 {len(errors)} 行解析失败，整份文件未上传；确认后可加 --skip-bad 跳过坏行")
        return 1
    if not readings:
        print("[错误] 没有可上传的读数")
        return 1
    try:
        with client_factory(args.api, token=args.token, username=args.username, password=args.password) as client:
            inserted, skipped = upload(client, args.field_id, args.sensor_key, readings, device=args.device,
                                       source=args.source, batch_size=args.batch_size)
    except ApiError as exc:
        print(f"[错误] 上传失败：{exc}（已成功的批次重传时会被平台跳过）")
        return 1
    print(f"[完成] 读入 {len(readings)} 条（坏行 {len(errors)}），新增 {inserted}，重复跳过 {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
