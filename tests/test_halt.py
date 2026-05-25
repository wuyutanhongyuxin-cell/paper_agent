"""halt 单元测试 —— M-D.2 spec §D.4 halt mechanism (PO MIT score_delta.py 借入).

覆盖：
  - score_delta 逐维 + 总分 abs delta
  - detect_halt 5 类退出：
      * exit 0 = running (halt=False) / converged (显式 user_signal_converged)
      * exit 1 = iter-cap (history ≥ iter_cap)
      * exit 2 = plateau (streak 满足 + 还未到 cap)
      * exit 3 = error (empty / 异常)
      * exit 4 = halt-by-user (显式 user_signal_halt=True)
  - paper-agnostic：history 中 paper_id 不影响算法
"""
from __future__ import annotations

import pytest

from paper_agent.score.dimensions import (
    DIMENSIONS,
    DimensionScore,
    EvidenceRef,
    Scored,
)
from paper_agent.score.halt import (
    HaltDecision,
    aggregate_score,
    detect_halt,
    score_delta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scored(*per_dim_scores: int, paper_id: str = "test") -> Scored:
    """生成一个 7-dim Scored，scores 顺序对应 DIMENSIONS。"""
    if len(per_dim_scores) != 7:
        raise ValueError(f"需要 7 个 score，给了 {len(per_dim_scores)}")
    dims = {
        d: DimensionScore(
            score=per_dim_scores[i],
            reasoning="",
            evidence=[],
            run_scores=[],
        )
        for i, d in enumerate(DIMENSIONS)
    }
    return Scored(
        paper_id=paper_id,
        scored_at="2026-05-25T10:00:00Z",
        dimensions=dims,
    )


# ---------------------------------------------------------------------------
# score_delta
# ---------------------------------------------------------------------------


def test_score_delta_returns_seven_dims_plus_total():
    prev = _scored(70, 70, 70, 70, 70, 70, 70)
    curr = _scored(75, 60, 70, 70, 70, 70, 70)
    delta = score_delta(prev, curr)
    # 7 dim + total
    for d in DIMENSIONS:
        assert d in delta
    assert "total" in delta


def test_score_delta_per_dim_abs_value():
    prev = _scored(70, 70, 70, 70, 70, 70, 70)
    curr = _scored(75, 60, 70, 70, 70, 70, 70)  # +5, -10, 0, 0, 0, 0, 0
    delta = score_delta(prev, curr)
    assert delta["rigor"] == 5.0
    assert delta["novelty"] == 10.0  # abs
    assert delta["clarity"] == 0.0


def test_score_delta_total_is_abs_aggregate_diff():
    """total delta = abs(sum(curr) - sum(prev))。"""
    prev = _scored(70, 70, 70, 70, 70, 70, 70)  # sum=490
    curr = _scored(75, 60, 70, 70, 70, 70, 70)  # sum=485, diff=-5
    delta = score_delta(prev, curr)
    assert delta["total"] == 5.0


def test_score_delta_zero_when_identical():
    s1 = _scored(70, 70, 70, 70, 70, 70, 70)
    s2 = _scored(70, 70, 70, 70, 70, 70, 70)
    delta = score_delta(s1, s2)
    for v in delta.values():
        assert v == 0.0


# ---------------------------------------------------------------------------
# aggregate_score helper
# ---------------------------------------------------------------------------


def test_aggregate_score_is_sum_over_dims():
    s = _scored(70, 71, 72, 73, 74, 75, 76)  # 511
    assert aggregate_score(s) == 511.0


# ---------------------------------------------------------------------------
# detect_halt — error & user signals
# ---------------------------------------------------------------------------


def test_detect_halt_empty_history_is_error():
    """空 history → exit_code=3 error。"""
    result = detect_halt([])
    assert result.halt is True
    assert result.exit_code == 3
    assert "empty" in result.reason.lower() or "error" in result.reason.lower()


def test_detect_halt_user_signal_halt_returns_exit_4():
    """user_signal_halt=True → exit_code=4 halt-by-user，无视 history。"""
    history = [_scored(70, 70, 70, 70, 70, 70, 70)]
    result = detect_halt(history, user_signal_halt=True)
    assert result.halt is True
    assert result.exit_code == 4
    assert "user" in result.reason.lower()


def test_detect_halt_user_signal_converged_returns_exit_0():
    """user_signal_converged=True → halt=True + exit_code=0 converged。"""
    history = [_scored(85, 85, 85, 85, 85, 85, 85)]
    result = detect_halt(history, user_signal_converged=True)
    assert result.halt is True
    assert result.exit_code == 0
    assert "converged" in result.reason.lower()


# ---------------------------------------------------------------------------
# detect_halt — iter cap
# ---------------------------------------------------------------------------


def test_detect_halt_below_iter_cap_continues():
    """len(history)=1 < iter_cap=3 → halt=False, exit_code=0 running。"""
    history = [_scored(70, 70, 70, 70, 70, 70, 70)]
    result = detect_halt(history, iter_cap=3)
    assert result.halt is False
    assert result.exit_code == 0


def test_detect_halt_at_iter_cap_returns_exit_1():
    """len(history) == iter_cap=3 → halt=True, exit_code=1 iter-cap。

    且 delta 较大 (>= threshold)，确保是 iter-cap 而非 plateau。
    """
    history = [
        _scored(50, 50, 50, 50, 50, 50, 50),
        _scored(60, 60, 60, 60, 60, 60, 60),  # delta=70
        _scored(70, 70, 70, 70, 70, 70, 70),  # delta=70
    ]
    result = detect_halt(history, iter_cap=3, plateau_threshold=1.0)
    assert result.halt is True
    assert result.exit_code == 1
    assert "iter" in result.reason.lower() or "cap" in result.reason.lower()


def test_detect_halt_iter_cap_zero_halts_with_one_element():
    """iter_cap=0 → 任何 non-empty history 都立即 iter-cap。"""
    history = [_scored(70, 70, 70, 70, 70, 70, 70)]
    result = detect_halt(history, iter_cap=0)
    assert result.halt is True
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# detect_halt — plateau
# ---------------------------------------------------------------------------


def test_detect_halt_plateau_streak_satisfied_returns_exit_2():
    """连续 plateau_streak=3 次 total delta < threshold → exit_code=2 plateau。

    history 长度 = 4（base + 3 个 delta），每个 delta=0 < threshold=1.0。
    """
    history = [
        _scored(60, 60, 60, 60, 60, 60, 60),
        _scored(60, 60, 60, 60, 60, 60, 60),  # delta=0
        _scored(60, 60, 60, 60, 60, 60, 60),  # delta=0
        _scored(60, 60, 60, 60, 60, 60, 60),  # delta=0
    ]
    result = detect_halt(history, iter_cap=10, plateau_streak=3, plateau_threshold=1.0)
    assert result.halt is True
    assert result.exit_code == 2
    assert "plateau" in result.reason.lower()


def test_detect_halt_plateau_streak_not_satisfied_continues():
    """只有 2 次 delta < threshold（streak=3 需要 3 次）→ halt=False。"""
    history = [
        _scored(60, 60, 60, 60, 60, 60, 60),
        _scored(60, 60, 60, 60, 60, 60, 60),
        _scored(60, 60, 60, 60, 60, 60, 60),  # 只有 2 个 delta，不够 3
    ]
    result = detect_halt(history, iter_cap=10, plateau_streak=3, plateau_threshold=1.0)
    assert result.halt is False
    assert result.exit_code == 0


def test_detect_halt_recent_jump_breaks_plateau():
    """最近一次 delta 较大 → streak 重置 → halt=False。"""
    history = [
        _scored(60, 60, 60, 60, 60, 60, 60),
        _scored(60, 60, 60, 60, 60, 60, 60),  # delta=0
        _scored(60, 60, 60, 60, 60, 60, 60),  # delta=0
        _scored(70, 70, 70, 70, 70, 70, 70),  # delta=70 — 打破 streak
    ]
    result = detect_halt(history, iter_cap=10, plateau_streak=3, plateau_threshold=1.0)
    assert result.halt is False


def test_detect_halt_iter_cap_takes_precedence_over_plateau():
    """如果 plateau streak 满足且 history < iter_cap → plateau (exit 2)；
    如果 history >= iter_cap 同时 streak 满足 → iter-cap (exit 1) 优先。

    spec 排序：先 iter-cap 防 budget 失控，再 plateau。
    """
    # 6 元素 history，streak 满足，iter_cap=4
    history = [_scored(60, 60, 60, 60, 60, 60, 60) for _ in range(6)]
    result = detect_halt(history, iter_cap=4, plateau_streak=3, plateau_threshold=1.0)
    assert result.halt is True
    # iter_cap=4，history 6 ≥ 4 → iter-cap 优先
    assert result.exit_code == 1


def test_detect_halt_plateau_threshold_strict_less():
    """delta == threshold 是否算 plateau？规约：< threshold 才算 (strict)。"""
    history = [
        _scored(60, 60, 60, 60, 60, 60, 60),
        _scored(61, 60, 60, 60, 60, 60, 60),  # total delta=1
        _scored(62, 60, 60, 60, 60, 60, 60),  # total delta=1
        _scored(63, 60, 60, 60, 60, 60, 60),  # total delta=1
    ]
    # delta=1.0 = threshold → NOT plateau (strict <)
    result = detect_halt(history, iter_cap=10, plateau_streak=3, plateau_threshold=1.0)
    assert result.halt is False


# ---------------------------------------------------------------------------
# HaltDecision frozen
# ---------------------------------------------------------------------------


def test_halt_decision_is_frozen():
    d = HaltDecision(halt=False, exit_code=0, reason="running", iteration=1)
    with pytest.raises((AttributeError, TypeError)):
        d.halt = True  # type: ignore[misc]


def test_halt_decision_iteration_field():
    """HaltDecision 含 iteration 字段，等于 len(history)。"""
    history = [_scored(70, 70, 70, 70, 70, 70, 70)]
    result = detect_halt(history)
    assert result.iteration == 1
