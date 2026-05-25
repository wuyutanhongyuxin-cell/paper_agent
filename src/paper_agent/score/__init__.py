"""paper-agent score core — 0.1.1 M-D.

paper-agnostic 7-dim scoring schema + halt mechanism. LLM 调用 stub 出，
M-E ensemble 模块再注入 evaluator。L-033 read-only：本子包永不写 paper.tex。
"""
from .dimensions import (
    DIMENSIONS,
    DimensionScore,
    EvidenceRef,
    Scored,
    derive_confidence,
    score_tier,
)

__all__ = [
    "DIMENSIONS",
    "DimensionScore",
    "EvidenceRef",
    "Scored",
    "derive_confidence",
    "score_tier",
]

# halt 模块在 M-D.5 加进来时会扩展 __all__
try:
    from .halt import HaltDecision, detect_halt, score_delta  # noqa: F401
    __all__ += ["HaltDecision", "detect_halt", "score_delta"]
except ImportError:  # pragma: no cover — M-D.5 之前 halt.py 尚未存在
    pass
