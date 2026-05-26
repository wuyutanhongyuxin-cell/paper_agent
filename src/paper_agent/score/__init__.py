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

# red_team 模块在 M-E.1 加进来时扩展 __all__
try:
    from .red_team import (  # noqa: F401
        CHECKS,
        DEFAULT_FAILURE_MODES,
        RedTeamCheck,
        RedTeamFinding,
        SAFE_REVISION_RE,
        is_safe_revision,
        run_red_team,
    )
    __all__ += [
        "CHECKS",
        "DEFAULT_FAILURE_MODES",
        "RedTeamCheck",
        "RedTeamFinding",
        "SAFE_REVISION_RE",
        "is_safe_revision",
        "run_red_team",
    ]
except ImportError:  # pragma: no cover — M-E.1 之前 red_team.py 尚未存在
    pass

# ensemble 模块在 M-E.2 加进来时扩展 __all__
try:
    from .ensemble import (  # noqa: F401
        area_chair_aggregate,
        ensemble_alpha,
        krippendorff_alpha_interval,
        num_reviews_ensemble,
    )
    __all__ += [
        "area_chair_aggregate",
        "ensemble_alpha",
        "krippendorff_alpha_interval",
        "num_reviews_ensemble",
    ]
except ImportError:  # pragma: no cover — M-E.2 之前 ensemble.py 尚未存在
    pass
