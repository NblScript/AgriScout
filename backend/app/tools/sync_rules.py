"""YAML 规则同步：以 rules/ 目录为源，按 rule_key 幂等 upsert 到 Rule 表。

用法：
    cd backend && .venv/bin/python -m app.tools.sync_rules
也可经接口触发：POST /api/v1/rules/sync-yaml

纪律（决策注册表「规则引擎生命周期」）：只停用不删除；内容变更 version 自增；解析失败的文件整体拒绝。

与规则修订审批的衔接：审批通过的修订案直接写规则表（rule_revision.apply_draft_to_rule）。
若 YAML 尚未回写同样的改动，常规同步会把审批结果悄悄覆盖回旧内容——因此
当前版本来自审批且与 YAML 不一致的规则会被跳过并记入 conflicts，
需人工把审批内容回写 YAML（推荐）或显式 --force 以 YAML 为准覆盖。
回写完成后首次同步会记入 reconciled，此后该规则的 YAML 修改按正常更新处理。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Crop, Rule, RuleRevision
from app.schemas.rule import RuleCreate

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"  # backend/rules/

_CONTENT_FIELDS = ("tier", "condition", "action", "params", "priority", "crop_id", "source")


def _fingerprint(data: dict) -> str:
    payload = {k: data.get(k) for k in _CONTENT_FIELDS}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _approved_revision_owning(db: Session, rule: Rule) -> RuleRevision | None:
    """规则当前内容若来自尚未回写 YAML 的审批修订案，返回该修订案。

    - deactivate 不改内容（版本号也不变），不参与内容冲突判断；
    - 已对齐（yaml_reconciled_at 非空）的修订案不再「拥有」规则——此后 YAML 的修改是正常更新。
    """
    return db.scalars(
        select(RuleRevision)
        .where(
            RuleRevision.rule_key == rule.rule_key,
            RuleRevision.status == "approved",
            RuleRevision.action.in_(("modify", "add")),
            RuleRevision.applied_version == rule.version,
            RuleRevision.yaml_reconciled_at.is_(None),
        )
        .order_by(RuleRevision.id.desc())
    ).first()


def sync_rules(db: Session, directory: Path | None = None, *, force: bool = False) -> dict:
    """force=True：即使规则当前版本来自审批修订案，也以 YAML 为准覆盖。"""
    directory = directory or RULES_DIR
    files = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
    if not files:
        raise FileNotFoundError(f"未找到规则文件：{directory}")

    stats: dict = {
        "files": len(files), "created": 0, "updated": 0, "unchanged": 0,
        "errors": [], "conflicts": [], "reconciled": [],
    }
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
            elif _fingerprint(new_data) != _fingerprint(
                {f: getattr(existing, f) for f in new_data}
            ):
                # 显式 getattr 取值（__dict__ 在属性 expired/deferred 时会缺键导致误判变更）
                revision = None if force else _approved_revision_owning(db, existing)
                if revision is not None:
                    stats["conflicts"].append(
                        f"{new_data['rule_key']} 当前 v{existing.version} 来自修订案 #{revision.id} 审批，"
                        "与 YAML 不一致，已跳过：请把审批内容回写 YAML，或以 --force 用 YAML 覆盖"
                    )
                    continue
                for key, value in new_data.items():
                    setattr(existing, key, value)
                existing.version += 1  # 内容变更 → 版本自增，进后续快照
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
                # YAML 已与审批结果一致（人工回写完成）：打标对齐，之后 YAML 修改按正常更新处理
                revision = _approved_revision_owning(db, existing)
                if revision is not None:
                    revision.yaml_reconciled_at = datetime.now(timezone.utc)
                    stats["reconciled"].append(f"{existing.rule_key}（修订案 #{revision.id}）")
    db.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    db = SessionLocal()
    try:
        stats = sync_rules(db, force="--force" in args)
    finally:
        db.close()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 1 if stats.get("errors") or stats.get("conflicts") else 0


if __name__ == "__main__":
    sys.exit(main())
