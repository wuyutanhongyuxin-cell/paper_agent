"""score/dimensions.py — paper-agent 0.1.1 7-dim scoring schema (M-D.1).

实现 spec §D.3：

- 7 维评分维度（顺序锁死）：rigor / novelty / clarity / reproducibility /
  related / significance / ethics
- Anti-inflation 7 档区间锚（详见 src/paper_agent/score/prompts/scoring_anchors.md）
- self_reliability_alpha 三段 confidence（high / low / fail）
- Scored / DimensionScore / EvidenceRef dataclass + JSON round-trip

paper-agnostic 承诺：
- 7 维字段固定为 schema contract，meanings 全部 generic
- paper_id 完全来自 CLI 参数，永不 hardcode 学科 / 语言 / paper-specific 信息
- score 模块不读 / 写 paper.tex（L-033 read-only）
- 仅写自己的 scored_<ts>.json 到 out/

LLM 集成（5 run ensemble / Krippendorff α / Area Chair aggregate）是 M-E
`score/ensemble.py` 范围。M-D 仅暴露 schema + evaluator 接口契约。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


# ---------------------------------------------------------------------------
# 7 个维度（spec §D.3 顺序锁死）
# ---------------------------------------------------------------------------

DIMENSIONS: tuple[str, ...] = (
    "rigor",
    "novelty",
    "clarity",
    "reproducibility",
    "related",
    "significance",
    "ethics",
)


# ---------------------------------------------------------------------------
# Anti-inflation 7 档区间锚（spec §D.3 + prompts/scoring_anchors.md）
# ---------------------------------------------------------------------------

_TIER_RANGES: tuple[tuple[int, int, str], ...] = (
    (0, 20, "fatally flawed"),
    (21, 40, "substantially flawed"),
    (41, 55, "significant issues"),
    (56, 70, "acceptable"),
    (71, 85, "strong"),
    (86, 92, "excellent"),
    (93, 100, "exceptional"),
)


def score_tier(score: int) -> str:
    """spec §D.3 Anti-inflation 7 档区间锚 → 强制 LLM 先选区间。

    Args:
        score: 0-100 闭区间整数

    Returns:
        档位 label 字符串

    Raises:
        ValueError: score 超出 [0, 100]
    """
    if not isinstance(score, int) and not (isinstance(score, float) and score.is_integer()):
        raise ValueError(f"score must be int, got {type(score).__name__}={score!r}")
    s = int(score)
    if s < 0 or s > 100:
        raise ValueError(f"score must be in [0, 100], got {s}")
    for lo, hi, label in _TIER_RANGES:
        if lo <= s <= hi:
            return label
    raise ValueError(f"score {s} did not match any tier — internal logic error")  # pragma: no cover


# ---------------------------------------------------------------------------
# Self-reliability α confidence 三段（spec §D.3 + Rating Roulette EMNLP 2025）
# ---------------------------------------------------------------------------

ConfidenceLabel = Literal["high", "low", "fail"]


def derive_confidence(
    alpha: float | None,
    *,
    min_threshold: float = 0.67,
    target_threshold: float = 0.80,
) -> ConfidenceLabel:
    """spec §D.3 self-reliability α → confidence label 三段映射。

    | α range           | confidence | downstream |
    |-------------------|------------|------------|
    | α ≥ target        | "high"     | 达标          |
    | min ≤ α < target  | "low"      | 低置信通过      |
    | α < min / None    | "fail"     | 重跑或人工介入    |

    Args:
        alpha: Krippendorff α self-reliability，M-D 默认 None
        min_threshold: 0.67 (Krippendorff 2004 acceptable line)
        target_threshold: 0.80 (substantial agreement)
    """
    if alpha is None:
        return "fail"
    if alpha >= target_threshold:
        return "high"
    if alpha >= min_threshold:
        return "low"
    return "fail"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRef:
    """LLM 引用的具体行号锚 —— `paper-agent verify-score` 用 `grep -n` 反查。

    frozen=True 防止 LLM 后期回填污染。
    """
    file: str
    line: int


@dataclass
class DimensionScore:
    """单维评分（spec §D.3 schema 单元素）。

    - score: 0-100 整数
    - reasoning: LLM 解释（中文 / 英文均可）
    - evidence: 行号锚列表
    - run_scores: ensemble runs 数组（M-D 默认空，M-E 填充 5 元素）
    """
    score: int
    reasoning: str
    evidence: list[EvidenceRef]
    run_scores: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reasoning": self.reasoning,
            "evidence": [asdict(e) for e in self.evidence],
            "run_scores": list(self.run_scores),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DimensionScore":
        evidence_raw = data.get("evidence", [])
        evidence = [
            EvidenceRef(file=e["file"], line=int(e["line"])) for e in evidence_raw
        ]
        return cls(
            score=int(data["score"]),
            reasoning=str(data.get("reasoning", "")),
            evidence=evidence,
            run_scores=list(data.get("run_scores", [])),
        )


@dataclass
class Scored:
    """spec §D.3 顶层 scored.json 容器。

    paper_id / scored_at 完全 CLI 参数化（通用化承诺）。dimensions 字段
    必须含 7 维所有 key，from_json 会校验。
    """
    paper_id: str
    scored_at: str
    dimensions: dict[str, DimensionScore]
    ensemble_runs: int = 1
    self_reliability_alpha: float | None = None
    alpha_min_threshold: float = 0.67
    alpha_target_threshold: float = 0.80
    red_team_findings: list[dict[str, Any]] = field(default_factory=list)
    version: str = "0.1.1"

    def __post_init__(self) -> None:
        missing = set(DIMENSIONS) - set(self.dimensions.keys())
        extra = set(self.dimensions.keys()) - set(DIMENSIONS)
        if missing or extra:
            raise ValueError(
                f"dimensions key mismatch: missing={sorted(missing)} extra={sorted(extra)}; "
                f"expected exactly {list(DIMENSIONS)}"
            )

    @property
    def confidence(self) -> ConfidenceLabel:
        return derive_confidence(
            self.self_reliability_alpha,
            min_threshold=self.alpha_min_threshold,
            target_threshold=self.alpha_target_threshold,
        )

    @property
    def alpha_pass(self) -> bool:
        a = self.self_reliability_alpha
        return a is not None and a >= self.alpha_min_threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "paper_id": self.paper_id,
            "scored_at": self.scored_at,
            "ensemble_runs": self.ensemble_runs,
            "dimensions": {d: self.dimensions[d].to_dict() for d in DIMENSIONS},
            "self_reliability_alpha": self.self_reliability_alpha,
            "alpha_min_threshold": self.alpha_min_threshold,
            "alpha_target_threshold": self.alpha_target_threshold,
            "alpha_pass": self.alpha_pass,
            "confidence": self.confidence,
            "red_team_findings": list(self.red_team_findings),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scored":
        dims_raw = data.get("dimensions")
        if not isinstance(dims_raw, dict):
            raise ValueError("Scored.dimensions must be a JSON object")
        dims = {k: DimensionScore.from_dict(v) for k, v in dims_raw.items()}
        return cls(
            paper_id=str(data.get("paper_id", "")),
            scored_at=str(data.get("scored_at", "")),
            dimensions=dims,
            ensemble_runs=int(data.get("ensemble_runs", 1)),
            self_reliability_alpha=(
                None if data.get("self_reliability_alpha") is None
                else float(data["self_reliability_alpha"])
            ),
            alpha_min_threshold=float(data.get("alpha_min_threshold", 0.67)),
            alpha_target_threshold=float(data.get("alpha_target_threshold", 0.80)),
            red_team_findings=list(data.get("red_team_findings", [])),
            version=str(data.get("version", "0.1.1")),
        )

    @classmethod
    def from_json(cls, blob: str) -> "Scored":
        data = json.loads(blob)
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Module-level CLI: --dump-template
# ---------------------------------------------------------------------------


def _make_empty_template(paper_id: str) -> Scored:
    """生成 7 dim 全 placeholder 的空模板（每维 score=0，reasoning="", evidence=[]）。

    供 LLM evaluator 或人工逐维填写。
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dims = {
        d: DimensionScore(score=0, reasoning="", evidence=[], run_scores=[])
        for d in DIMENSIONS
    }
    return Scored(paper_id=paper_id, scored_at=now, dimensions=dims)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m paper_agent.score.dimensions",
        description="7-dim scoring schema utility (M-D paper-agent 0.1.1).",
    )
    parser.add_argument(
        "--dump-template",
        action="store_true",
        help="Dump empty 7-dim scored.json template to --out (or stdout).",
    )
    parser.add_argument(
        "--paper-id",
        type=str,
        default="",
        help="Paper identifier (CLI-injected, never hardcoded).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output file path. If omitted, dump to stdout.",
    )
    args = parser.parse_args(argv)

    if args.dump_template:
        if not args.paper_id:
            print("[FAIL] --dump-template requires --paper-id", file=sys.stderr)
            return 1
        scored = _make_empty_template(args.paper_id)
        blob = scored.to_json()
        if args.out is None:
            print(blob)
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(blob, encoding="utf-8")
            print(f"[dimensions] template -> {args.out}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
