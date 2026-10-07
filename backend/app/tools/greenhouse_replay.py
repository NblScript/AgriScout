"""大棚巡检策略离线比较 CLI（计划 0017）：大棚真值 JSON（可多个种子）→ Markdown + JSON 报告。

用法（不连数据库，只读真值文件）：
    cd simulator && for s in 1 2 3; do ../backend/.venv/bin/python greenhouse_run.py --offline --days 30 --seed $s; done
    cd backend && .venv/bin/python -m app.tools.greenhouse_replay --truth ../simulator/out/greenhouse-truth-*.json

策略和指标的定义见 services/greenhouse_replay.py；风险策略调用的是线上同一份 patrol_planner。
报告开头写明「模拟结论只证明流程」：病害规律是按设计放进模拟器的，数字不能当作效果证据（D5）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services.greenhouse_replay import STRATEGIES, ReplayParams, render_markdown, run_replay


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="大棚巡检策略离线比较（模拟结论只证明流程）")
    ap.add_argument("--truth", nargs="+", required=True, type=Path, help="greenhouse_run.py 导出的真值文件，可多个")
    ap.add_argument("--fixed-every", type=int, default=3, help="固定巡检的全覆盖周期（天）")
    ap.add_argument("--human-budget", type=int, default=5, help="每天人工确认上限（各策略相同）")
    ap.add_argument("--photo-cap", type=int, default=None, help="每天照片上限（各策略相同），默认 ceil(2 × 株数 / 周期)")
    ap.add_argument("--strategies", nargs="+", default=list(STRATEGIES), choices=STRATEGIES)
    ap.add_argument("--out", type=Path, default=None, help="报告路径前缀，默认 <第一个真值所在目录>/greenhouse-replay")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = ReplayParams(fixed_every_days=args.fixed_every, human_budget=args.human_budget,
                              photo_cap=args.photo_cap, strategies=tuple(args.strategies))
        truths = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(set(args.truth))]
        report = run_replay(truths, params)
    except (OSError, ValueError, KeyError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    markdown = render_markdown(report)
    prefix = args.out or sorted(set(args.truth))[0].parent / "greenhouse-replay"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".md").write_text(markdown, encoding="utf-8")
    prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(markdown)
    print(f"[导出] {prefix.with_suffix('.md')} / {prefix.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
