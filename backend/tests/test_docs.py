"""文档系统机械校验（harness-engineering 实践）：
AGENTS.md 行数上限、内部链接可解析、db-schema 快照新鲜度、执行计划必备节。
文档烂了这里先红——让文档腐烂和让测试失败同罪。
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENTS = REPO / "AGENTS.md"
DOCS = REPO / "docs"

# 校验范围的入口文件：这些文件里的 [](...) 与 [text]: path 链接必须指向真实文件
LINK_CHECK_FILES = [
    AGENTS,
    REPO / "ARCHITECTURE.md",
    DOCS / "design-docs" / "index.md",
    DOCS / "design-docs" / "core-beliefs.md",
    DOCS / "design-docs" / "decision-registry.md",
    DOCS / "exec-plans" / "README.md",
    DOCS / "product-specs" / "index.md",
]

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def test_agents_md_exists_and_is_a_map():
    """AGENTS.md 是地图不是说明书：存在、有导航表、不超过 120 行。"""
    assert AGENTS.exists(), "AGENTS.md 缺失——代理入口没了"
    text = AGENTS.read_text(encoding="utf-8")
    lines = text.count("\n")
    assert lines <= 120, f"AGENTS.md 已 {lines} 行（上限 120）——瘦身为地图，细节移到 docs/"
    assert "文档导航" in text, "缺少文档导航节——地图要指向下一步"
    assert "红线" in text, "缺少红线节——不可变约束必须写在这里"


def test_internal_links_resolve():
    """入口文档里的相对链接必须指向仓库内真实文件。"""
    broken = []
    for md in LINK_CHECK_FILES:
        if not md.exists():
            broken.append(f"{md.relative_to(REPO)}（文件本身缺失）")
            continue
        for target in MD_LINK.findall(md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{md.relative_to(REPO)} → {target}")
    assert not broken, f"断裂链接：{broken}"


def test_exec_plans_have_required_sections():
    """active 计划必备三节：状态/决策记录/进度（接手会话的最低信息保障）。"""
    active = DOCS / "exec-plans" / "active"
    required = ("## 状态", "## 决策记录", "## 进度")
    problems = []
    for plan in active.glob("*.md"):
        text = plan.read_text(encoding="utf-8")
        for section in required:
            if section not in text:
                problems.append(f"{plan.name} 缺 {section}")
    assert not problems, problems


def test_db_schema_snapshot_fresh():
    """db-schema.md 必须与当前模型一致：改表后重跑 gen_db_schema。"""
    sys.path.insert(0, str(REPO / "backend" / "app" / "tools"))
    from gen_db_schema import render  # noqa: E402

    snapshot = DOCS / "generated" / "db-schema.md"
    assert snapshot.exists(), "docs/generated/db-schema.md 缺失——运行 python -m app.tools.gen_db_schema"
    current = render()
    committed = snapshot.read_text(encoding="utf-8")
    assert committed == current, (
        "db-schema.md 过期——表结构已变："
        "cd backend && .venv/bin/python -m app.tools.gen_db_schema"
    )
