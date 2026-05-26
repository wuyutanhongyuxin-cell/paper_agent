"""score/ensemble.py — paper-agent 0.1.1 num_reviews_ensemble + Area Chair (M-E.2).

实现 spec §D.4 ensemble contract：
  - `num_reviews_ensemble` 反复跑 evaluator 收集 n 个 Scored
  - `krippendorff_alpha_interval` 纯数学 Krippendorff α (interval-level)
  - `ensemble_alpha` 把 n 个 Scored 映射到 self-reliability α
  - `area_chair_aggregate` 取每维 median + α 标注 + evidence 去重

LLM evaluator 由调用方注入。M-E 本身只声明 evaluator 接口契约
`(paper_path, paper_id, run_idx) -> Scored`，不带任何 prompt / model
hardcode；M-F 真 LLM 后端再接入。

paper-agnostic 承诺：
  - paper_id 完全 CLI / 调用方参数化
  - α 算法纯数学 (Hayes & Krippendorff 2007), 跨学科可消费
  - L-033 read-only: ensemble 永不写 paper.tex, 仅写 out/aggregate_*.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from .dimensions import DIMENSIONS, DimensionScore, EvidenceRef, Scored


# ---------------------------------------------------------------------------
# Krippendorff α (interval-level)
# ---------------------------------------------------------------------------


def krippendorff_alpha_interval(units: Sequence[Sequence[float]]) -> float | None:
    """Krippendorff α for interval-level data (Hayes & Krippendorff 2007).

    Args:
        units: list of units; each unit is a list of ratings (≥1 per unit).
               Units with < 2 ratings contribute 0 to observed disagreement.

    Returns:
        α in [-1, 1], or None if insufficient data (no valid within-unit pairs).

    Convention:
        - 所有观察值完全相同 (Do=De=0) → α=1.0 (退化的 perfect agreement)
        - 所有 unit 只有 1 rating → 无法算 → None
        - 空输入 → None
    """
    valid = [list(u) for u in units if len(u) >= 2]
    if not valid:
        return None

    all_obs = [x for u in units for x in u]
    n_total = len(all_obs)
    if n_total < 2:
        return None

    # 观察值 disagreement: 每 unit 内所有有序对 (i, j) 平方差 / (m_u - 1)
    Do = 0.0
    for unit in valid:
        m = len(unit)
        denom = m - 1
        for i in range(m):
            for j in range(m):
                if i == j:
                    continue
                Do += (unit[i] - unit[j]) ** 2 / denom

    # 期望 disagreement: 全 pool 中所有有序对 (i, j) 平方差 / (n_total - 1)
    De = 0.0
    for i in range(n_total):
        for j in range(n_total):
            if i == j:
                continue
            De += (all_obs[i] - all_obs[j]) ** 2 / (n_total - 1)

    if De == 0:
        # 全体观察值都相同 (单一数值): 视为 perfect agreement
        return 1.0 if Do == 0 else None

    return 1.0 - Do / De


def ensemble_alpha(runs: list[Scored]) -> float | None:
    """把 n 个 Scored 映射到 self-reliability α (interval-level Krippendorff).

    Treats each of the 7 DIMENSIONS as one unit; each run contributes one
    rating per unit (= the Scored.dimensions[d].score). α answers: do the
    ratings within the same dimension agree more than across dimensions?

    Returns None if insufficient data (< 2 runs).
    """
    if len(runs) < 2:
        return None
    units = [[r.dimensions[d].score for r in runs] for d in DIMENSIONS]
    return krippendorff_alpha_interval(units)


# ---------------------------------------------------------------------------
# num_reviews_ensemble
# ---------------------------------------------------------------------------


EvaluatorFn = Callable[[Path, str, int], Scored]


def num_reviews_ensemble(
    evaluator: EvaluatorFn,
    paper_path: Path,
    *,
    n_runs: int = 3,
    paper_id: str = "",
) -> list[Scored]:
    """跑 evaluator n 次，收集 Scored 列表。

    Args:
        evaluator: callable (paper_path, paper_id, run_idx) -> Scored
        paper_path: 论文路径 (L-033 read-only — 本函数只传, 不写)
        n_runs: 调用次数 (≥0)
        paper_id: 论文标识 (CLI 参数化, 永不 hardcode)

    Returns:
        list[Scored] (长度 = n_runs)
    """
    if n_runs < 0:
        raise ValueError(f"n_runs must be >= 0, got {n_runs}")
    return [evaluator(paper_path, paper_id, i) for i in range(n_runs)]


# ---------------------------------------------------------------------------
# area_chair_aggregate
# ---------------------------------------------------------------------------


def _dedupe_evidence(items: list[EvidenceRef]) -> list[EvidenceRef]:
    """按 (file, line) 去重并保持遇见顺序。"""
    seen: set[tuple[str, int]] = set()
    out: list[EvidenceRef] = []
    for e in items:
        key = (e.file, e.line)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def area_chair_aggregate(
    runs: list[Scored],
    *,
    paper_id: str,
    scored_at: str | None = None,
) -> Scored:
    """spec §D.4 Area Chair: 每维 median + α 标注 + evidence 去重.

    Args:
        runs: 时序无关的 Scored 列表 (n_runs 次独立评)
        paper_id: 终值 paper_id (上层指定, 覆盖各 run 中可能不一致的 id)
        scored_at: ISO-8601 时间戳；None 则填当前 UTC

    Returns:
        聚合后的 Scored (ensemble_runs=N, self_reliability_alpha 已算).

    Raises:
        ValueError: runs 为空
    """
    if not runs:
        raise ValueError("area_chair_aggregate: runs must be non-empty")

    if scored_at is None:
        scored_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    n_runs = len(runs)
    alpha = ensemble_alpha(runs) if n_runs >= 2 else None

    # 每维 aggregate
    agg_dims: dict[str, DimensionScore] = {}
    for d in DIMENSIONS:
        per_run_scores = [r.dimensions[d].score for r in runs]
        median_score = int(statistics.median(per_run_scores))
        # reasoning: 取 first run 的；M-F LLM 再决定要不要合并
        first_reasoning = runs[0].dimensions[d].reasoning
        agg_reasoning = (
            f"[ensemble of {n_runs} runs, median={median_score}] {first_reasoning}"
        )
        # evidence 跨 run union + dedupe
        all_evidence: list[EvidenceRef] = []
        for r in runs:
            all_evidence.extend(r.dimensions[d].evidence)
        deduped = _dedupe_evidence(all_evidence)

        agg_dims[d] = DimensionScore(
            score=median_score,
            reasoning=agg_reasoning,
            evidence=deduped,
            run_scores=per_run_scores,
        )

    # red_team_findings 合并 (上层去重责任)
    combined_red_team: list[dict] = []
    for r in runs:
        combined_red_team.extend(r.red_team_findings)

    # alpha thresholds 取 first run 的 (通常各 run 默认一致)
    return Scored(
        paper_id=paper_id,
        scored_at=scored_at,
        dimensions=agg_dims,
        ensemble_runs=n_runs,
        self_reliability_alpha=alpha,
        alpha_min_threshold=runs[0].alpha_min_threshold,
        alpha_target_threshold=runs[0].alpha_target_threshold,
        red_team_findings=combined_red_team,
        version=runs[0].version,
    )


# ---------------------------------------------------------------------------
# Module-level CLI
# ---------------------------------------------------------------------------


def _load_runs_from_dir(runs_dir: Path) -> list[Scored]:
    if not runs_dir.exists() or not runs_dir.is_dir():
        return []
    files = sorted(runs_dir.glob("scored_*.json"))
    out: list[Scored] = []
    for f in files:
        try:
            out.append(Scored.from_json(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[ensemble] skip {f.name}: {e}", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m paper_agent.score.ensemble",
        description="num_reviews_ensemble + Area Chair aggregate (M-E paper-agent 0.1.1).",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        required=True,
        help="Directory containing scored_*.json files from independent runs.",
    )
    parser.add_argument(
        "--paper-id",
        type=str,
        required=True,
        help="Paper identifier for the aggregated output (CLI-injected).",
    )
    parser.add_argument(
        "--scored-at",
        type=str,
        default=None,
        help="ISO-8601 timestamp; defaults to current UTC.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional aggregate output path; defaults to stdout.",
    )
    args = parser.parse_args(argv)

    if not args.runs_dir.exists() or not args.runs_dir.is_dir():
        print(f"[FAIL] runs-dir not found: {args.runs_dir}", file=sys.stderr)
        return 2

    runs = _load_runs_from_dir(args.runs_dir)
    if not runs:
        print(f"[FAIL] no scored_*.json under {args.runs_dir}", file=sys.stderr)
        return 3

    agg = area_chair_aggregate(
        runs,
        paper_id=args.paper_id,
        scored_at=args.scored_at,
    )
    blob = agg.to_json(indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob, encoding="utf-8")
        print(f"[ensemble] aggregate -> {args.out}")
    else:
        print(blob)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
