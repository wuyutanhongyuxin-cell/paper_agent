"""dimensions 单元测试 —— M-D.1 spec §D.3 7-dim scoring schema.

覆盖：
  - DIMENSIONS 是 7 元 frozen tuple，顺序锁死
  - EvidenceRef / DimensionScore / Scored dataclass round-trip
  - score_tier 7 档区间锚（0-20 / 21-40 / 41-55 / 56-70 / 71-85 / 86-92 / 93-100）
  - score_tier 越界 ValueError
  - derive_confidence 4 个区间（None / <0.67 / 0.67-0.80 / ≥0.80）
  - 中文 reasoning UTF-8 序列化
  - evidence 反序列化恢复 EvidenceRef 类型
  - paper_id 通用化注入（non_aphasia_cs fixture 路径）
  - L-033 read-only：score 模块不触 paper.tex
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from paper_agent.score.dimensions import (
    DIMENSIONS,
    DimensionScore,
    EvidenceRef,
    Scored,
    derive_confidence,
    score_tier,
)

CS_FIXTURE = Path(__file__).parent / "fixtures" / "non_aphasia_cs"


# ---------------------------------------------------------------------------
# DIMENSIONS frozen contract
# ---------------------------------------------------------------------------


def test_dimensions_is_seven_tuple():
    assert isinstance(DIMENSIONS, tuple)
    assert len(DIMENSIONS) == 7


def test_dimensions_order_is_locked():
    """spec §D.3 规定的字段顺序，不许重排。"""
    assert DIMENSIONS == (
        "rigor",
        "novelty",
        "clarity",
        "reproducibility",
        "related",
        "significance",
        "ethics",
    )


def test_dimensions_is_immutable():
    """tuple 本身不可 append，验证 frozen 语义。"""
    with pytest.raises((AttributeError, TypeError)):
        DIMENSIONS.append("extra")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# EvidenceRef
# ---------------------------------------------------------------------------


def test_evidence_ref_basic():
    ev = EvidenceRef(file="src/paper.tex", line=234)
    assert ev.file == "src/paper.tex"
    assert ev.line == 234


def test_evidence_ref_frozen():
    """EvidenceRef 应是 frozen dataclass —— 防止 LLM 后期回填污染。"""
    ev = EvidenceRef(file="a.tex", line=1)
    with pytest.raises((AttributeError, TypeError)):
        ev.file = "b.tex"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DimensionScore round-trip
# ---------------------------------------------------------------------------


def test_dimension_score_basic():
    ds = DimensionScore(
        score=75,
        reasoning="清晰的方法学描述",
        evidence=[EvidenceRef(file="src/paper.tex", line=100)],
        run_scores=[74, 76, 75, 75, 75],
    )
    assert ds.score == 75
    assert ds.run_scores == [74, 76, 75, 75, 75]


def test_dimension_score_empty_runs_allowed():
    """M-D ensemble_runs=1，run_scores 允许为空（M-E 才填）。"""
    ds = DimensionScore(score=70, reasoning="placeholder", evidence=[], run_scores=[])
    assert ds.run_scores == []


# ---------------------------------------------------------------------------
# score_tier — 8 个边界 + ValueError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_label",
    [
        (0, "fatally flawed"),
        (20, "fatally flawed"),
        (21, "substantially flawed"),
        (40, "substantially flawed"),
        (41, "significant issues"),
        (55, "significant issues"),
        (56, "acceptable"),
        (70, "acceptable"),
        (71, "strong"),
        (85, "strong"),
        (86, "excellent"),
        (92, "excellent"),
        (93, "exceptional"),
        (100, "exceptional"),
    ],
)
def test_score_tier_boundaries(score: int, expected_label: str):
    """spec §D.3 anti-inflation 7 档区间锚，所有边界都必须命中正确档。"""
    assert score_tier(score) == expected_label


def test_score_tier_negative_raises():
    with pytest.raises(ValueError):
        score_tier(-1)


def test_score_tier_over_100_raises():
    with pytest.raises(ValueError):
        score_tier(101)


# ---------------------------------------------------------------------------
# derive_confidence — 4 个区间
# ---------------------------------------------------------------------------


def test_derive_confidence_none_alpha_is_fail():
    """α=None（M-D 默认）→ fail；M-E ensemble 才填数。"""
    assert derive_confidence(None) == "fail"


def test_derive_confidence_below_min_is_fail():
    assert derive_confidence(0.66) == "fail"
    assert derive_confidence(0.0) == "fail"


def test_derive_confidence_min_inclusive_is_low():
    """0.67 ≤ α < 0.80 → low；0.67 边界包含进 low。"""
    assert derive_confidence(0.67) == "low"
    assert derive_confidence(0.75) == "low"
    assert derive_confidence(0.799) == "low"


def test_derive_confidence_target_inclusive_is_high():
    """α ≥ 0.80 → high；0.80 边界包含进 high。"""
    assert derive_confidence(0.80) == "high"
    assert derive_confidence(0.85) == "high"
    assert derive_confidence(1.0) == "high"


def test_derive_confidence_custom_thresholds():
    """thresholds 可 CLI override（通用化）。"""
    assert derive_confidence(0.5, min_threshold=0.4, target_threshold=0.7) == "low"
    assert derive_confidence(0.71, min_threshold=0.4, target_threshold=0.7) == "high"


# ---------------------------------------------------------------------------
# Scored round-trip JSON
# ---------------------------------------------------------------------------


def _make_full_scored(paper_id: str = "test") -> Scored:
    dims = {
        d: DimensionScore(
            score=70,
            reasoning=f"reasoning for {d}",
            evidence=[EvidenceRef(file="src/paper.tex", line=i * 10)],
            run_scores=[],
        )
        for i, d in enumerate(DIMENSIONS, start=1)
    }
    return Scored(
        paper_id=paper_id,
        scored_at="2026-05-25T10:00:00Z",
        dimensions=dims,
    )


def test_scored_requires_all_seven_dims():
    """Scored 必须包含 7 个 dim，缺一抛 ValueError。"""
    partial = {d: DimensionScore(score=0, reasoning="", evidence=[], run_scores=[])
               for d in DIMENSIONS[:6]}
    with pytest.raises(ValueError, match="dimensions"):
        Scored(paper_id="p", scored_at="2026-05-25T10:00:00Z", dimensions=partial)


def test_scored_round_trip_json():
    """to_json → from_json 全 7 dim 字段保留。"""
    original = _make_full_scored("paper-001")
    blob = original.to_json()
    restored = Scored.from_json(blob)
    assert restored.paper_id == "paper-001"
    assert restored.scored_at == "2026-05-25T10:00:00Z"
    assert set(restored.dimensions.keys()) == set(DIMENSIONS)
    for d in DIMENSIONS:
        assert restored.dimensions[d].score == 70


def test_scored_round_trip_preserves_evidence_type():
    """evidence list 反序列化后是 EvidenceRef 实例，不是 dict。"""
    original = _make_full_scored()
    restored = Scored.from_json(original.to_json())
    rigor_evidence = restored.dimensions["rigor"].evidence
    assert len(rigor_evidence) == 1
    assert isinstance(rigor_evidence[0], EvidenceRef)
    assert rigor_evidence[0].file == "src/paper.tex"
    assert rigor_evidence[0].line == 10


def test_scored_chinese_reasoning_utf8():
    """中文 reasoning 必须 UTF-8 序列化，反序后字节级一致。"""
    scored = _make_full_scored()
    scored.dimensions["rigor"] = DimensionScore(
        score=75,
        reasoning="本研究使用混合效应模型，统计假设清晰",
        evidence=[],
        run_scores=[],
    )
    blob = scored.to_json()
    # ensure_ascii=False 保证中文字符直接出现
    assert "本研究" in blob
    assert "混合效应" in blob
    restored = Scored.from_json(blob)
    assert restored.dimensions["rigor"].reasoning == "本研究使用混合效应模型，统计假设清晰"


def test_scored_default_confidence_is_fail():
    """M-D 默认 α=None → confidence=fail（M-E 重算）。"""
    scored = _make_full_scored()
    assert scored.confidence == "fail"
    assert scored.self_reliability_alpha is None


def test_scored_version_locked():
    """version 字段固定为 0.1.1，不许变。"""
    scored = _make_full_scored()
    assert scored.version == "0.1.1"
    blob = scored.to_json()
    restored = Scored.from_json(blob)
    assert restored.version == "0.1.1"


# ---------------------------------------------------------------------------
# 通用化承诺：paper_id 注入 + 非失语症 fixture
# ---------------------------------------------------------------------------


def test_scored_paper_id_is_not_hardcoded(tmp_path):
    """通用化承诺：paper_id 完全来自 CLI 参数，与 fixture 无耦合。"""
    for pid in ["aphasia-zh-2026-05", "non_aphasia_cs", "anonymous-001", ""]:
        s = _make_full_scored(paper_id=pid)
        assert s.paper_id == pid
        # round-trip 也保住
        restored = Scored.from_json(s.to_json())
        assert restored.paper_id == pid


def test_scored_dump_against_cs_fixture(tmp_path):
    """对 non_aphasia_cs fixture 跑 dump-template 路径，验证 paper-agnostic。

    通用化合规 ([[feedback_paper_agent_long_term_generality]])：score/ 模块
    不应假定任何学科。cs 论文 paper_id 也能正常生成 scored.json 模板。
    """
    work = tmp_path / "cs"
    shutil.copytree(CS_FIXTURE, work)

    scored = _make_full_scored(paper_id="non_aphasia_cs")
    out = tmp_path / "scored_cs.json"
    out.write_text(scored.to_json(), encoding="utf-8")

    restored = Scored.from_json(out.read_text(encoding="utf-8"))
    assert restored.paper_id == "non_aphasia_cs"
    assert set(restored.dimensions.keys()) == set(DIMENSIONS)


def test_score_module_is_read_only_against_paper_tex(tmp_path):
    """L-033 read-only：score schema 模块不应该读 / 写 paper.tex。

    我们不强制 score 跑 audit。但这个测试保证：
    创建 Scored、序列化、反序列化 全程不需要 paper.tex 文件存在。
    """
    work = tmp_path / "no_paper_tex"
    work.mkdir()
    # 故意不创建 paper.tex
    assert not (work / "src" / "paper.tex").exists()

    s = _make_full_scored(paper_id="ghost-paper")
    blob = s.to_json()
    Scored.from_json(blob)  # 必须不抛错
    # paper.tex 仍然不存在
    assert not (work / "src" / "paper.tex").exists()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_scored_from_json_invalid_dims_raises():
    """JSON 缺 dim → from_json 抛 ValueError。"""
    bad = json.dumps({
        "version": "0.1.1",
        "paper_id": "x",
        "scored_at": "2026-05-25T10:00:00Z",
        "dimensions": {"rigor": {"score": 70, "reasoning": "", "evidence": [], "run_scores": []}},
    })
    with pytest.raises(ValueError):
        Scored.from_json(bad)


def test_scored_dimensions_extra_key_raises():
    """JSON 多了未知 dim → from_json 抛 ValueError（schema lock）。"""
    dims = {d: {"score": 0, "reasoning": "", "evidence": [], "run_scores": []} for d in DIMENSIONS}
    dims["extra_dim"] = {"score": 0, "reasoning": "", "evidence": [], "run_scores": []}
    bad = json.dumps({
        "version": "0.1.1",
        "paper_id": "x",
        "scored_at": "2026-05-25T10:00:00Z",
        "dimensions": dims,
    })
    with pytest.raises(ValueError):
        Scored.from_json(bad)
