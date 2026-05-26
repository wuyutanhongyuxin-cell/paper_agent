"""ensemble 单元测试 — M-E.2 spec §D.4 num_reviews_ensemble + Krippendorff α + Area Chair aggregate.

覆盖：
  - krippendorff_alpha_interval 纯数学边界 (perfect agreement / high variance / degenerate)
  - num_reviews_ensemble 调用 evaluator n_runs 次，run_idx / paper_id 传递正确
  - area_chair_aggregate: median per dim + α annotated + evidence dedup + 7-dim contract
  - paper-agnostic: non_aphasia_cs fixture + 任意 paper_id 跑通
  - L-033 read-only: 不修改 paper.tex
  - CLI smoke
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_agent.score.dimensions import (
    DIMENSIONS,
    DimensionScore,
    EvidenceRef,
    Scored,
)
from paper_agent.score.ensemble import (
    area_chair_aggregate,
    ensemble_alpha,
    krippendorff_alpha_interval,
    main as ensemble_cli,
    num_reviews_ensemble,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_scored(
    *,
    paper_id: str = "test",
    scored_at: str = "2026-05-26T00:00:00Z",
    per_dim: dict[str, int] | None = None,
    evidence: dict[str, list[EvidenceRef]] | None = None,
    reasoning_prefix: str = "",
) -> Scored:
    """Build a Scored with per-dim scores (default 70 each)."""
    if per_dim is None:
        per_dim = {d: 70 for d in DIMENSIONS}
    if evidence is None:
        evidence = {d: [] for d in DIMENSIONS}
    dims = {
        d: DimensionScore(
            score=per_dim[d],
            reasoning=f"{reasoning_prefix}{d}",
            evidence=evidence.get(d, []),
            run_scores=[per_dim[d]],
        )
        for d in DIMENSIONS
    }
    return Scored(paper_id=paper_id, scored_at=scored_at, dimensions=dims)


# ---------------------------------------------------------------------------
# krippendorff_alpha_interval
# ---------------------------------------------------------------------------


def test_alpha_perfect_within_units_returns_one():
    """各 unit 内部无变异 (每个 dim 在所有 run 上分数相同), 但 unit 之间有差异 → α = 1.0。"""
    # 7 dims, each with 3 identical ratings, varying across dims
    units = [[70, 70, 70], [60, 60, 60], [80, 80, 80], [50, 50, 50],
             [90, 90, 90], [65, 65, 65], [75, 75, 75]]
    alpha = krippendorff_alpha_interval(units)
    assert alpha is not None
    assert alpha == pytest.approx(1.0, abs=1e-9)


def test_alpha_high_within_unit_variance_is_low():
    """unit 内部变异大 → α 降低。"""
    units = [[10, 90, 50], [10, 90, 50], [10, 90, 50], [10, 90, 50],
             [10, 90, 50], [10, 90, 50], [10, 90, 50]]
    alpha = krippendorff_alpha_interval(units)
    assert alpha is not None
    # 每 unit 内方差占总方差的全部 → α ≤ 0
    assert alpha < 0.1


def test_alpha_returns_none_for_empty():
    assert krippendorff_alpha_interval([]) is None


def test_alpha_returns_none_for_all_single_rating_units():
    """所有 unit 只有 1 个 rating → 无法算 within-unit disagreement → None。"""
    assert krippendorff_alpha_interval([[70], [60], [80]]) is None


def test_alpha_zero_de_handling():
    """所有观察值相同 (Do=De=0) → 视为 perfect agreement, α=1.0。"""
    units = [[70, 70, 70], [70, 70, 70], [70, 70, 70]]
    alpha = krippendorff_alpha_interval(units)
    # 全相同时退化情况，约定返回 1.0
    assert alpha == 1.0 or alpha is None  # 任一约定，但不能 crash


def test_alpha_mild_variance_intermediate():
    """中等变异 → α 在 (0, 1) 区间。"""
    units = [[70, 72, 68], [60, 62, 58], [80, 82, 78], [50, 52, 48],
             [90, 88, 92], [65, 67, 63], [75, 73, 77]]
    alpha = krippendorff_alpha_interval(units)
    assert alpha is not None
    assert 0.5 < alpha < 1.0


# ---------------------------------------------------------------------------
# ensemble_alpha (Scored runs → single α)
# ---------------------------------------------------------------------------


def test_ensemble_alpha_perfect_runs():
    """3 个完全相同的 Scored → α=1.0。"""
    runs = [_mk_scored() for _ in range(3)]
    alpha = ensemble_alpha(runs)
    assert alpha == pytest.approx(1.0, abs=1e-9)


def test_ensemble_alpha_drifted_runs():
    """3 run 内部稍有漂移 → α 高但 < 1.0。"""
    runs = [
        _mk_scored(per_dim={"rigor": 70, "novelty": 60, "clarity": 80,
                            "reproducibility": 50, "related": 90,
                            "significance": 65, "ethics": 75}),
        _mk_scored(per_dim={"rigor": 72, "novelty": 62, "clarity": 78,
                            "reproducibility": 52, "related": 88,
                            "significance": 67, "ethics": 73}),
        _mk_scored(per_dim={"rigor": 68, "novelty": 58, "clarity": 82,
                            "reproducibility": 48, "related": 92,
                            "significance": 63, "ethics": 77}),
    ]
    alpha = ensemble_alpha(runs)
    assert alpha is not None
    assert 0.5 < alpha < 1.0


def test_ensemble_alpha_empty_returns_none():
    assert ensemble_alpha([]) is None


def test_ensemble_alpha_single_run_returns_none():
    """1 个 run → 各 unit 只有 1 rating → 无法算 α。"""
    runs = [_mk_scored()]
    assert ensemble_alpha(runs) is None


# ---------------------------------------------------------------------------
# num_reviews_ensemble
# ---------------------------------------------------------------------------


def test_num_reviews_ensemble_calls_evaluator_n_times(tmp_path):
    """evaluator 被调用 n_runs 次。"""
    paper = tmp_path / "paper.tex"
    paper.write_text("dummy", encoding="utf-8")

    call_count = {"n": 0}

    def stub_eval(paper_path: Path, paper_id: str, run_idx: int) -> Scored:
        call_count["n"] += 1
        return _mk_scored(paper_id=paper_id)

    runs = num_reviews_ensemble(stub_eval, paper, n_runs=5, paper_id="x")
    assert call_count["n"] == 5
    assert len(runs) == 5


def test_num_reviews_ensemble_run_idx_distinct(tmp_path):
    """每次调用 run_idx ∈ [0, n_runs)。"""
    paper = tmp_path / "paper.tex"
    paper.write_text("dummy", encoding="utf-8")
    seen: list[int] = []

    def stub_eval(paper_path: Path, paper_id: str, run_idx: int) -> Scored:
        seen.append(run_idx)
        return _mk_scored()

    num_reviews_ensemble(stub_eval, paper, n_runs=4, paper_id="x")
    assert seen == [0, 1, 2, 3]


def test_num_reviews_ensemble_paper_id_propagates(tmp_path):
    """evaluator 收到正确的 paper_id。"""
    paper = tmp_path / "paper.tex"
    paper.write_text("dummy", encoding="utf-8")
    ids: list[str] = []

    def stub_eval(paper_path: Path, paper_id: str, run_idx: int) -> Scored:
        ids.append(paper_id)
        return _mk_scored(paper_id=paper_id)

    num_reviews_ensemble(stub_eval, paper, n_runs=2, paper_id="some-paper")
    assert ids == ["some-paper", "some-paper"]


def test_num_reviews_ensemble_zero_runs_returns_empty(tmp_path):
    paper = tmp_path / "paper.tex"
    paper.write_text("dummy", encoding="utf-8")

    def stub_eval(p, pid, i):
        raise AssertionError("should not be called")

    out = num_reviews_ensemble(stub_eval, paper, n_runs=0, paper_id="x")
    assert out == []


def test_num_reviews_ensemble_negative_runs_raises(tmp_path):
    paper = tmp_path / "paper.tex"
    paper.write_text("dummy", encoding="utf-8")
    with pytest.raises(ValueError):
        num_reviews_ensemble(lambda *a: _mk_scored(), paper, n_runs=-1, paper_id="x")


# ---------------------------------------------------------------------------
# area_chair_aggregate
# ---------------------------------------------------------------------------


def test_area_chair_median_per_dim():
    """area_chair 取每维 median 作为终值。"""
    runs = [
        _mk_scored(per_dim={d: 60 for d in DIMENSIONS}),
        _mk_scored(per_dim={d: 70 for d in DIMENSIONS}),
        _mk_scored(per_dim={d: 80 for d in DIMENSIONS}),
    ]
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    for d in DIMENSIONS:
        assert agg.dimensions[d].score == 70


def test_area_chair_median_odd_count():
    """3 runs: 50, 60, 80 → median = 60。"""
    runs = [
        _mk_scored(per_dim={"rigor": 50, **{d: 70 for d in DIMENSIONS if d != "rigor"}}),
        _mk_scored(per_dim={"rigor": 60, **{d: 70 for d in DIMENSIONS if d != "rigor"}}),
        _mk_scored(per_dim={"rigor": 80, **{d: 70 for d in DIMENSIONS if d != "rigor"}}),
    ]
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    assert agg.dimensions["rigor"].score == 60


def test_area_chair_preserves_dimensions_contract():
    """area_chair 输出 Scored 必含 7 dim。"""
    runs = [_mk_scored() for _ in range(3)]
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    assert set(agg.dimensions.keys()) == set(DIMENSIONS)


def test_area_chair_sets_ensemble_runs():
    runs = [_mk_scored() for _ in range(5)]
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    assert agg.ensemble_runs == 5


def test_area_chair_sets_self_reliability_alpha():
    """α 字段被填充。"""
    runs = [_mk_scored() for _ in range(3)]
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    # 3 个 identical runs → α=1.0 或 None (degenerate case)
    assert agg.self_reliability_alpha is None or agg.self_reliability_alpha == pytest.approx(1.0)


def test_area_chair_collects_run_scores_per_dim():
    """每维 run_scores 数组包含全部 N runs 的原始分。"""
    runs = [
        _mk_scored(per_dim={"rigor": 60, **{d: 70 for d in DIMENSIONS if d != "rigor"}}),
        _mk_scored(per_dim={"rigor": 70, **{d: 70 for d in DIMENSIONS if d != "rigor"}}),
        _mk_scored(per_dim={"rigor": 80, **{d: 70 for d in DIMENSIONS if d != "rigor"}}),
    ]
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    assert sorted(agg.dimensions["rigor"].run_scores) == [60, 70, 80]


def test_area_chair_dedupes_evidence():
    """跨 run 的 evidence 在终值中去重。"""
    ev = EvidenceRef(file="paper.tex", line=42)
    ev_dict = {d: [ev] for d in DIMENSIONS}
    runs = [_mk_scored(evidence=ev_dict) for _ in range(3)]
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    # 3 runs 都引用同一行 → 终值只剩 1 个
    assert len(agg.dimensions["rigor"].evidence) == 1
    assert agg.dimensions["rigor"].evidence[0] == ev


def test_area_chair_empty_runs_raises():
    with pytest.raises(ValueError):
        area_chair_aggregate([], paper_id="x", scored_at="now")


def test_area_chair_paper_id_override_used():
    """paper_id 参数覆盖 runs 中的 id (通用化承诺：上层指定优先)。"""
    runs = [_mk_scored(paper_id="run-id") for _ in range(3)]
    agg = area_chair_aggregate(runs, paper_id="override-id", scored_at="now")
    assert agg.paper_id == "override-id"


def test_area_chair_combines_red_team_findings():
    """合并各 run 的 red_team_findings。"""
    runs = []
    for i in range(3):
        s = _mk_scored()
        s.red_team_findings = [{"mode": "scope_overclaim", "run_idx": i}]
        runs.append(s)
    agg = area_chair_aggregate(runs, paper_id="x", scored_at="now")
    assert len(agg.red_team_findings) == 3


# ---------------------------------------------------------------------------
# paper-agnostic + L-033 read-only
# ---------------------------------------------------------------------------


_FIXTURE_TEX = Path(__file__).parent / "fixtures" / "non_aphasia_cs" / "src" / "paper.tex"


def test_ensemble_non_aphasia_cs_fixture():
    """CS paper fixture 跑 num_reviews_ensemble + area_chair_aggregate 不崩。"""
    assert _FIXTURE_TEX.exists()

    def stub_eval(paper_path: Path, paper_id: str, run_idx: int) -> Scored:
        # Deterministic scored: 70 + run_idx 给 rigor，70 其他
        per_dim = {d: 70 for d in DIMENSIONS}
        per_dim["rigor"] = 70 + run_idx
        return _mk_scored(paper_id=paper_id, per_dim=per_dim)

    runs = num_reviews_ensemble(stub_eval, _FIXTURE_TEX, n_runs=3, paper_id="non_aphasia_cs")
    agg = area_chair_aggregate(runs, paper_id="non_aphasia_cs", scored_at="2026-05-26T00:00:00Z")
    assert agg.paper_id == "non_aphasia_cs"
    assert agg.ensemble_runs == 3
    assert set(agg.dimensions.keys()) == set(DIMENSIONS)


def test_ensemble_does_not_modify_paper_tex(tmp_path):
    """L-033: ensemble 不写 paper.tex。"""
    paper = tmp_path / "paper.tex"
    paper.write_text("original", encoding="utf-8")
    before_mtime = paper.stat().st_mtime_ns

    def stub_eval(p, pid, i):
        return _mk_scored()

    num_reviews_ensemble(stub_eval, paper, n_runs=3, paper_id="x")
    assert paper.read_text(encoding="utf-8") == "original"
    assert paper.stat().st_mtime_ns == before_mtime


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_ensemble_aggregate_from_runs_dir(tmp_path):
    """python -m paper_agent.score.ensemble --runs-dir D --out F → 读多个 scored_*.json + aggregate。"""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    for i in range(3):
        s = _mk_scored(paper_id=f"run-{i}", scored_at=f"2026-05-26T0{i}:00:00Z")
        (runs_dir / f"scored_{i:03d}.json").write_text(s.to_json(), encoding="utf-8")

    out = tmp_path / "aggregate.json"
    rc = ensemble_cli([
        "--runs-dir", str(runs_dir),
        "--paper-id", "agg-paper",
        "--scored-at", "2026-05-26T10:00:00Z",
        "--out", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["paper_id"] == "agg-paper"
    assert data["ensemble_runs"] == 3
    assert set(data["dimensions"].keys()) == set(DIMENSIONS)


def test_cli_ensemble_no_runs_dir_returns_nonzero(tmp_path):
    rc = ensemble_cli([
        "--runs-dir", str(tmp_path / "does-not-exist"),
        "--paper-id", "x",
        "--scored-at", "now",
    ])
    assert rc != 0
