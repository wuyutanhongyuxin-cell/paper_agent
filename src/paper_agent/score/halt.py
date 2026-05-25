"""score/halt.py — paper-agent 0.1.1 halt mechanism (M-D.2).

实现 spec §D.4 halt rules：PaperOrchestra MIT `score_delta.py` ~175 行整段
引入语义，固化到 paper-agent score/ 子包。

设计（5 个 exit code）：

| exit_code | 名称           | 触发条件 |
|-----------|----------------|---------|
| 0         | converged / running | user_signal_converged=True 显式收敛；或 halt=False 仍在跑 |
| 1         | iter-cap       | len(history) >= iter_cap，budget exhausted，必停 |
| 2         | plateau        | 最近 plateau_streak 次 total delta 严格 < threshold + 未到 cap |
| 3         | error          | 异常（empty history 等） |
| 4         | halt-by-user   | user_signal_halt=True 显式中止 |

优先级（高到低）：error > halt-by-user > converged > iter-cap > plateau > running

paper-agnostic 承诺：
- score_delta 仅依赖 Scored.dimensions 数值，不识别 paper_id / scored_at / 任何
  学科 / 语言 / paper-specific 字段
- 算法纯数学，跨学科可消费
- L-033 read-only：halt 模块只读 history，不写 paper.tex；它只决策是否继续 ensemble
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .dimensions import DIMENSIONS, Scored


# ---------------------------------------------------------------------------
# HaltDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HaltDecision:
    """halt 决策结果。

    halt=False → 继续 ensemble loop
    halt=True  → 停 loop，exit_code 表示停因
    """
    halt: bool
    exit_code: int
    reason: str
    iteration: int


# ---------------------------------------------------------------------------
# 评分聚合 + delta 计算
# ---------------------------------------------------------------------------


def aggregate_score(scored: Scored) -> float:
    """7 维分数总和（spec §D.4 plateau 判定基线）。"""
    return float(sum(scored.dimensions[d].score for d in DIMENSIONS))


def score_delta(prev: Scored, curr: Scored) -> dict[str, float]:
    """逐维 + 总分 abs delta（PaperOrchestra `score_delta.py` 借入语义）。

    Returns:
        {"rigor": Δ, ..., "ethics": Δ, "total": Δ_total} 共 8 个 float key，
        每个值都是 abs(curr - prev)。
    """
    out: dict[str, float] = {}
    for d in DIMENSIONS:
        diff = curr.dimensions[d].score - prev.dimensions[d].score
        out[d] = float(abs(diff))
    out["total"] = abs(aggregate_score(curr) - aggregate_score(prev))
    return out


def _consecutive_total_deltas(history: list[Scored]) -> list[float]:
    """从 history 计算相邻两次的 total abs delta，长度 = len(history) - 1。"""
    out: list[float] = []
    for i in range(1, len(history)):
        out.append(score_delta(history[i - 1], history[i])["total"])
    return out


# ---------------------------------------------------------------------------
# detect_halt
# ---------------------------------------------------------------------------


def detect_halt(
    history: list[Scored],
    *,
    iter_cap: int = 3,
    plateau_streak: int = 3,
    plateau_threshold: float = 1.0,
    user_signal_halt: bool = False,
    user_signal_converged: bool = False,
) -> HaltDecision:
    """spec §D.4 halt 决策。优先级 error > halt-by-user > converged > iter-cap > plateau > running。

    Args:
        history: 时序排序的 Scored 列表（最早 → 最新），代表已完成的 ensemble runs
        iter_cap: 最大允许的 iter 数（防 budget 失控）。len(history) ≥ iter_cap 必停。
        plateau_streak: 连续多少次 total delta < threshold 触发 plateau
        plateau_threshold: total delta 严格小于此值算 "no movement"
        user_signal_halt: 显式中止（exit 4）
        user_signal_converged: 显式收敛（exit 0 + halt=True）

    Returns:
        HaltDecision（含 halt / exit_code / reason / iteration）
    """
    n = len(history)

    # exit 3 — error
    if n == 0:
        return HaltDecision(
            halt=True,
            exit_code=3,
            reason="error: empty history, cannot decide halt",
            iteration=0,
        )

    # exit 4 — halt-by-user (优先级高于一切非 error 状态)
    if user_signal_halt:
        return HaltDecision(
            halt=True,
            exit_code=4,
            reason="halt-by-user: explicit user_signal_halt=True",
            iteration=n,
        )

    # exit 0 — converged (user 显式表示已满意；高于 iter-cap)
    if user_signal_converged:
        return HaltDecision(
            halt=True,
            exit_code=0,
            reason="converged: explicit user_signal_converged=True",
            iteration=n,
        )

    # exit 1 — iter-cap (budget exhausted，优先于 plateau 以确保停)
    if n >= iter_cap:
        return HaltDecision(
            halt=True,
            exit_code=1,
            reason=f"iter-cap: history length {n} >= iter_cap {iter_cap}",
            iteration=n,
        )

    # exit 2 — plateau
    deltas = _consecutive_total_deltas(history)
    if len(deltas) >= plateau_streak:
        last_streak = deltas[-plateau_streak:]
        if all(d < plateau_threshold for d in last_streak):
            return HaltDecision(
                halt=True,
                exit_code=2,
                reason=(
                    f"plateau: last {plateau_streak} total deltas all < "
                    f"{plateau_threshold} (got {last_streak})"
                ),
                iteration=n,
            )

    # running
    return HaltDecision(
        halt=False,
        exit_code=0,
        reason=f"running: iteration {n}/{iter_cap}, no halt condition met",
        iteration=n,
    )


# ---------------------------------------------------------------------------
# Module-level CLI
# ---------------------------------------------------------------------------


def _load_history(history_dir: Path) -> list[Scored]:
    """从目录读 scored_*.json 按文件名排序载入。"""
    if not history_dir.exists() or not history_dir.is_dir():
        return []
    files = sorted(history_dir.glob("scored_*.json"))
    out: list[Scored] = []
    for f in files:
        try:
            out.append(Scored.from_json(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[halt] skipping {f.name}: {e}", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m paper_agent.score.halt",
        description="Halt decision for ensemble scoring loop (M-D paper-agent 0.1.1).",
    )
    parser.add_argument(
        "--history",
        type=Path,
        required=True,
        help="Directory containing scored_*.json files (time-ordered).",
    )
    parser.add_argument("--iter-cap", type=int, default=3)
    parser.add_argument("--plateau-streak", type=int, default=3)
    parser.add_argument("--plateau-threshold", type=float, default=1.0)
    parser.add_argument("--user-signal-halt", action="store_true")
    parser.add_argument("--user-signal-converged", action="store_true")
    parser.add_argument("--out", type=Path, default=None, help="Optional halt_decision.json path.")
    args = parser.parse_args(argv)

    history = _load_history(args.history)
    decision = detect_halt(
        history,
        iter_cap=args.iter_cap,
        plateau_streak=args.plateau_streak,
        plateau_threshold=args.plateau_threshold,
        user_signal_halt=args.user_signal_halt,
        user_signal_converged=args.user_signal_converged,
    )

    payload = {
        "halt": decision.halt,
        "exit_code": decision.exit_code,
        "reason": decision.reason,
        "iteration": decision.iteration,
    }
    blob = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob, encoding="utf-8")
        print(f"[halt] decision -> {args.out}")
    print(blob)
    return decision.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
