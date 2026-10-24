"""dm-cls 评估（执行计划 0019）：选结构只看验证集，测试集最后只跑一次。

报告：
1. 整叶二分类指标（霜霉病为阳性）：阈值 0.5 与「验证集召回 ≥ 0.9 的最高阈值」各一次，按来源分开报；
2. 误报检查（只在 --split test）：其他叶部病害（不参与训练）被判成霜霉病的比例，按原类别分报。

用法：
    .venv/bin/python eval_dm.py --run dm-cls-v1 --split val    # 结构比较，写 runs/<run>/eval-val.json
    .venv/bin/python eval_dm.py --run dm-cls-v1                # 测试集，写 runs/<run>/eval.json，export_model.py --kind dm 读它
"""
import argparse
import json
import math
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent
DATA_DIR = ML_ROOT / "data" / "dm_cls"
POSITIVE = "downy_mildew"
DEFAULT_THRESHOLD = 0.5
MIN_RECALL = 0.9  # 巡检是筛查：漏报比误报贵


def pick_threshold(labels: list[int], probs: list[float], min_recall: float = MIN_RECALL,
                   default: float = DEFAULT_THRESHOLD) -> float:
    """召回率 ≥ min_recall 的最高阈值（概率 ≥ 阈值判为霜霉病）；没有阳性时返回默认值。"""
    positives = sorted((p for y, p in zip(labels, probs) if y == 1), reverse=True)
    if not positives:
        return default
    need = max(1, math.ceil(min_recall * len(positives) - 1e-9))
    return positives[need - 1]


def main() -> None:
    import numpy as np
    from ultralytics import YOLO

    from eval_rust import binary_metrics

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="dm-cls-v1")
    ap.add_argument("--split", choices=("val", "test"), default="test")
    ap.add_argument("--min-recall", type=float, default=MIN_RECALL)
    args = ap.parse_args()
    weights = ML_ROOT / "runs" / args.run / "weights" / "best.pt"
    if not weights.exists():
        raise SystemExit(f"找不到 {weights}——先运行 train_dm.py --name {args.run}")
    model = YOLO(str(weights))
    pos_idx = next(i for i, name in model.names.items() if name == POSITIVE)
    imgsz = (getattr(model, "ckpt", None) or {}).get("train_args", {}).get("imgsz", 224)
    index = json.loads((DATA_DIR / "index.json").read_text(encoding="utf-8"))

    def probs_for(items: list[dict]) -> list[float]:
        out = []
        paths = [str(DATA_DIR / it["file"]) for it in items]
        for start in range(0, len(paths), 128):
            for r in model.predict(paths[start:start + 128], imgsz=imgsz, verbose=False):
                out.append(float(r.probs.data[pos_idx]))
        return out

    def metrics(items: list[dict], probs: list[float], threshold: float) -> dict:
        y = np.array([1 if it["label"] == POSITIVE else 0 for it in items])
        result = binary_metrics(y, np.array(probs), threshold)
        result["threshold"] = round(threshold, 4)
        return result

    val_items = [it for it in index if it["split"] == "val"]
    val_probs = probs_for(val_items)
    tuned = pick_threshold([1 if it["label"] == POSITIVE else 0 for it in val_items], val_probs, args.min_recall)
    items, probs = (val_items, val_probs) if args.split == "val" else (
        [it for it in index if it["split"] == "test"], None)
    if probs is None:
        probs = probs_for(items)

    report = {"run": args.run, "split": args.split, "positive": POSITIVE,
              "tuned_threshold": {"value": round(tuned, 4), "rule": f"验证集召回 ≥ {args.min_recall} 的最高阈值"},
              "overall": {}, "by_source": {}}
    for name, thr in (("default", DEFAULT_THRESHOLD), ("tuned", tuned)):
        report["overall"][name] = metrics(items, probs, thr)
        for source in sorted({it["source"] for it in items}):
            pairs = [(it, p) for it, p in zip(items, probs) if it["source"] == source]
            report["by_source"].setdefault(source, {})[name] = metrics([a for a, _ in pairs], [b for _, b in pairs], thr)
        m = report["overall"][name]
        print(f"[{args.split}·阈值 {m['threshold']}] {m['n']} 张（霜霉病 {m['positives']}）P={m['precision']} "
              f"R={m['recall']} F1={m['f1']} ROC-AUC={m['roc_auc']} PR-AUC={m['pr_auc']}")

    if args.split == "test":
        heldout = [it for it in index if it["split"] == "heldout_other"]
        held_probs = probs_for(heldout) if heldout else []
        by_class: dict[str, dict] = {}
        for it, p in zip(heldout, held_probs):
            row = by_class.setdefault(f"{it['source']}/{it['source_class']}", {"n": 0, "default": 0, "tuned": 0})
            row["n"] += 1
            row["default"] += p >= DEFAULT_THRESHOLD
            row["tuned"] += p >= tuned
        report["false_alarm_other_diseases"] = {
            k: {"n": v["n"], "rate_default": round(v["default"] / v["n"], 4), "rate_tuned": round(v["tuned"] / v["n"], 4)}
            for k, v in sorted(by_class.items())}
        for k, v in report["false_alarm_other_diseases"].items():
            print(f"[误报] {k}：{v['n']} 张，判成霜霉病 {v['rate_default']:.1%}（阈值 0.5）/ {v['rate_tuned']:.1%}（调后阈值）")
        items, probs = items + heldout, probs + held_probs

    report["manifest"] = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    run_dir = ML_ROOT / "runs" / args.run
    out = run_dir / ("eval.json" if args.split == "test" else "eval-val.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    preds = [{"file": it["file"], "source": it["source"], "source_class": it["source_class"], "label": it["label"],
              "prob": round(p, 4)} for it, p in zip(items, probs)]
    (run_dir / f"predictions-{args.split}.json").write_text(json.dumps(preds, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
    print(f"[报告] {out}")


if __name__ == "__main__":
    main()
