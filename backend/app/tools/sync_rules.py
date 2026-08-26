"""YAML 规则同步：以 rules/ 目录为源，按 rule_key 幂等 upsert 到 Rule 表。

用法：
    cd backend && .venv/bin/python -m app.tools.sync_rules
也可经接口触发：POST /api/v1/rules/sync-yaml

纪律（docs/05）：只停用不删除；内容变更 version 自增；解析失败的文件整体拒绝。
"""
import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Crop, Rule
from app.schemas.rule import RuleCreate

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"  # backend/rules/

_CONTENT_FIELDS = ("tier", "condition", "action", "params", "priority", "crop_id", "source")


def _fingerprint(data: dict) -> str:
    payload = {k: data.get(k) for k in _CONTENT_FIELDS}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def sync_rules(db: Session, directory: Path | None = None) -> dict:
    directory = directory or RULES_DIR
    files = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
    if not files:
        raise FileNotFoundError(f"未找到规则文件：{directory}")

    stats: dict = {"files": len(files), "created": 0, "updated": 0, "unchanged": 0, "errors": []}
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            stats["errors"].append(f"{path.name}: YAML 解析失败 {exc}")
            continue
        entries = (doc or {}).get("rules") or []
        for entry in entries:
            crop_name = entry.pop("crop", None)
            crop_id = None
            if crop_name:
                crop_id = db.scalars(select(Crop.id).where(Crop.name == str(crop_name))).first()
                if crop_id is None:
                    stats["errors"].append(
                        f"{path.name}:{entry.get('rule_key')} 引用未知作物「{crop_name}」，跳过"
                    )
                    continue
            entry["crop_id"] = crop_id
            try:
                new_data = RuleCreate(**entry).model_dump()
            except Exception as exc:  # noqa: BLE001 校验失败单条记录，不中断整包
                stats["errors"].append(f"{path.name}:{entry.get('rule_key', '?')} {exc}")
                continue

            existing = db.scalars(
                select(Rule).where(Rule.rule_key == new_data["rule_key"])
            ).first()
            if existing is None:
                db.add(Rule(**new_data))
                stats["created"] += 1
            elif _fingerprint(new_data) != _fingerprint(existing.__dict__):
                # 先比对后修改：避免无变化写库，也保证不回滚掉本批次的待插入行
                for key, value in new_data.items():
                    setattr(existing, key, value)
                existing.version += 1  # 内容变更 → 版本自增，进后续快照
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
    db.commit()
    return stats


def main() -> int:
    db = SessionLocal()
    try:
        stats = sync_rules(db)
    finally:
        db.close()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 1 if stats.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
