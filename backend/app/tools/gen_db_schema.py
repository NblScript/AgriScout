"""生成 docs/generated/db-schema.md：从 SQLAlchemy metadata 导出字段级表结构。

用法：cd backend && .venv/bin/python -m app.tools.gen_db_schema
表结构变更后必须重新运行——backend/tests/test_docs.py 会校验快照新鲜度。
"""
from pathlib import Path

from app.models import Base

OUT = Path(__file__).resolve().parents[3] / "docs" / "generated" / "db-schema.md"

# 表的业务分组（与里程碑对应，便于阅读）
GROUPS = [
    ("基础管理（M1）", ["fields", "crops", "plantings", "devices"]),
    ("巡检接入（M2）", ["patrols", "capture_points", "weather_samples"]),
    ("分析与建议（M3/M4）", ["analyses", "rules", "advices"]),
    ("标注回流（M6+）", ["annotations"]),
]

TYPE_MAP = {
    "INTEGER": "Integer",
    "VARCHAR": "String",
    "TEXT": "Text",
    "DATETIME": "DateTime",
    "FLOAT": "Float",
    "BOOLEAN": "Boolean",
    "JSON": "JSON",
}


def render_default(server_default) -> str:
    """server_default → 稳定字符串（禁止内存地址等非确定输出，破坏快照比对）。"""
    arg = server_default.arg
    if hasattr(arg, "text"):  # TextClause，如 sa.text("now()")
        return arg.text
    if hasattr(arg, "name"):  # SQL 函数，如 func.now()
        return f"{arg.name}()"
    return str(arg)


def render() -> str:
    lines = [
        "# 数据库表结构（自动生成）",
        "",
        "> **勿手改**：由 `backend/app/tools/gen_db_schema.py` 从 SQLAlchemy metadata 生成。",
        "> 表结构变更后运行 `cd backend && .venv/bin/python -m app.tools.gen_db_schema` 重新生成，",
        "`test_docs.py` 会校验本文件与模型定义一致。",
        "",
    ]
    metadata = Base.metadata
    all_tables = set(metadata.tables)
    grouped = {t for _, tables in GROUPS for t in tables}
    groups = list(GROUPS) + [("其他", sorted(all_tables - grouped))]

    for title, tables in groups:
        existing = [t for t in tables if t in metadata.tables]
        if not existing:
            continue
        lines += [f"## {title}", ""]
        for table_name in existing:
            table = metadata.tables[table_name]
            comment = table.comment or ""
            lines += [f"### {table_name}" + (f" —— {comment}" if comment else ""), "",
                      "| 字段 | 类型 | 约束 | 说明 |", "|---|---|---|---|"]
            for col in table.columns:
                col_type = str(col.type)
                base_type = col_type.split("(")[0].upper()
                if base_type in TYPE_MAP and "(" in col_type:
                    shown = f"{TYPE_MAP[base_type]}{col_type[col_type.index('('):]}"
                else:
                    shown = TYPE_MAP.get(base_type, col_type)
                constraints = []
                if col.primary_key:
                    constraints.append("PK")
                if col.foreign_keys:
                    constraints.append("FK→" + ", ".join(
                        sorted(f"{fk.target_fullname}" for fk in col.foreign_keys)))
                if not col.nullable and not col.primary_key:
                    constraints.append("NOT NULL")
                if col.unique:
                    constraints.append("UNIQUE")
                if col.server_default is not None:
                    constraints.append(f"default={render_default(col.server_default)}")
                lines.append(f"| {col.name} | {shown} | {'、'.join(constraints) or '—'} | {col.comment or '—'} |")

            for idx in sorted(table.indexes, key=lambda i: i.name):
                cols = ", ".join(c.name for c in idx.columns)
                lines.append("")
                lines.append(f"索引 `{idx.name}`：({cols})" + ("（唯一）" if idx.unique else ""))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"已生成 {OUT}")
