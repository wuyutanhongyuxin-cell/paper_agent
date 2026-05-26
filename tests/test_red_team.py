"""red_team 单元测试 — M-E.1 spec §D.4 红队反诘 prompt 池.

覆盖：
  - DEFAULT_FAILURE_MODES 7 元 tuple 契约 (顺序锁死)
  - CHECKS registry 完整 / RedTeamCheck frozen
  - RedTeamFinding round-trip + frozen
  - run_red_team detector_regex 路径 (scope_overclaim 社工诱导词)
  - LLM-only modes 在无 evaluator 时静默 skip
  - LLM-only modes 在有 evaluator 时调用
  - L-033 read-only：run_red_team 不修改 paper.tex
  - is_safe_revision 白名单语义
  - paper-agnostic：paper_id 完全参数化；non_aphasia_cs fixture 跑通
  - CLI smoke
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from paper_agent.score.dimensions import EvidenceRef
from paper_agent.score.red_team import (
    CHECKS,
    DEFAULT_FAILURE_MODES,
    RedTeamCheck,
    RedTeamFinding,
    SAFE_REVISION_RE,
    is_safe_revision,
    main as red_team_cli,
    run_red_team,
)


# ---------------------------------------------------------------------------
# DEFAULT_FAILURE_MODES contract
# ---------------------------------------------------------------------------


def test_default_failure_modes_is_seven_tuple():
    assert isinstance(DEFAULT_FAILURE_MODES, tuple)
    assert len(DEFAULT_FAILURE_MODES) == 7


def test_default_failure_modes_order_locked():
    """spec §D.4 顺序锁死。"""
    assert DEFAULT_FAILURE_MODES == (
        "factual_fabrication",
        "methodology_handwave",
        "selective_reporting",
        "citation_inflation",
        "ethics_omission",
        "stat_misuse",
        "scope_overclaim",
    )


def test_default_failure_modes_is_immutable():
    with pytest.raises((AttributeError, TypeError)):
        DEFAULT_FAILURE_MODES[0] = "x"  # type: ignore[index]


# ---------------------------------------------------------------------------
# CHECKS registry
# ---------------------------------------------------------------------------


def test_checks_registry_covers_all_default_modes():
    modes_in_checks = {c.mode for c in CHECKS}
    assert modes_in_checks == set(DEFAULT_FAILURE_MODES)


def test_checks_severity_in_error_warn_info():
    for c in CHECKS:
        assert c.severity in {"ERROR", "WARN", "INFO"}, f"{c.mode}: {c.severity}"


def test_red_team_check_is_frozen():
    c = CHECKS[0]
    with pytest.raises((AttributeError, TypeError)):
        c.mode = "x"  # type: ignore[misc]


def test_each_check_has_non_empty_prompt_template():
    for c in CHECKS:
        assert isinstance(c.prompt_template, str)
        assert len(c.prompt_template.strip()) >= 20, f"{c.mode} prompt too short"


# ---------------------------------------------------------------------------
# RedTeamFinding
# ---------------------------------------------------------------------------


def test_red_team_finding_basic_construction():
    f = RedTeamFinding(
        mode="scope_overclaim",
        severity="WARN",
        message="overclaim detected",
        evidence=(EvidenceRef(file="paper.tex", line=42),),
    )
    assert f.mode == "scope_overclaim"
    assert f.severity == "WARN"
    assert f.evidence[0].line == 42
    assert f.safe_revision is False


def test_red_team_finding_default_safe_revision_false():
    f = RedTeamFinding(mode="stat_misuse", severity="WARN", message="x")
    assert f.safe_revision is False


def test_red_team_finding_is_frozen():
    f = RedTeamFinding(mode="ethics_omission", severity="ERROR", message="x")
    with pytest.raises((AttributeError, TypeError)):
        f.mode = "y"  # type: ignore[misc]


def test_red_team_finding_to_dict_roundtrip():
    f = RedTeamFinding(
        mode="scope_overclaim",
        severity="WARN",
        message="obvious overclaim",
        evidence=(EvidenceRef(file="paper.tex", line=10),),
        safe_revision=True,
    )
    d = f.to_dict()
    assert d["mode"] == "scope_overclaim"
    assert d["severity"] == "WARN"
    assert d["safe_revision"] is True
    assert d["evidence"] == [{"file": "paper.tex", "line": 10}]


# ---------------------------------------------------------------------------
# is_safe_revision + SAFE_REVISION_RE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "suggestion",
    [
        "replace phrase: foo with bar",
        "delete sentence: this is overclaim.",
        "reword clause: the obvious result is",
        "REPLACE PHRASE: case insensitive",
        "  replace phrase: leading whitespace tolerated  ",
    ],
)
def test_is_safe_revision_true(suggestion):
    assert is_safe_revision(suggestion) is True


@pytest.mark.parametrize(
    "suggestion",
    [
        "",
        "just rewrite the whole paragraph",
        "add a new claim: foo is bar",
        "modify the dataset and rerun",  # not in (replace|delete|reword) action verbs
        "replace paragraph: too coarse",   # not in (phrase|sentence|clause)
    ],
)
def test_is_safe_revision_false(suggestion):
    assert is_safe_revision(suggestion) is False


# ---------------------------------------------------------------------------
# run_red_team — detector_regex paths
# ---------------------------------------------------------------------------


def _write_tex(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "paper.tex"
    p.write_text(body, encoding="utf-8")
    return p


def test_run_red_team_scope_overclaim_detector_fires(tmp_path):
    """带 'obviously' / 'clearly demonstrates' 等社工诱导词 → 触发 scope_overclaim。"""
    body = (
        "\\section{Results}\n"
        "Our method obviously outperforms all baselines.\n"
        "This clearly demonstrates the superiority of our approach.\n"
    )
    tex = _write_tex(tmp_path, body)
    findings = run_red_team(tex, paper_id="test")
    overclaim = [f for f in findings if f.mode == "scope_overclaim"]
    assert len(overclaim) >= 1


def test_run_red_team_no_overclaim_on_neutral_tex(tmp_path):
    """中性论述 → 不触发 scope_overclaim detector。"""
    body = (
        "\\section{Results}\n"
        "Under the 16 GB memory constraint, IVF-PQ achieves Recall@10 = 0.94.\n"
        "HNSW exceeds the budget at 10M vectors.\n"
    )
    tex = _write_tex(tmp_path, body)
    findings = run_red_team(tex, paper_id="test")
    overclaim = [f for f in findings if f.mode == "scope_overclaim"]
    assert overclaim == []


def test_run_red_team_filters_by_modes(tmp_path):
    """传 modes=('scope_overclaim',) → 只跑该模式。"""
    body = "obviously the best method ever.\n"
    tex = _write_tex(tmp_path, body)
    findings = run_red_team(tex, modes=("scope_overclaim",), paper_id="test")
    assert all(f.mode == "scope_overclaim" for f in findings)


def test_run_red_team_unknown_mode_raises(tmp_path):
    tex = _write_tex(tmp_path, "x")
    with pytest.raises(ValueError):
        run_red_team(tex, modes=("not_a_real_mode",), paper_id="test")


# ---------------------------------------------------------------------------
# L-033 read-only
# ---------------------------------------------------------------------------


def test_run_red_team_does_not_modify_tex(tmp_path):
    """L-033: run_red_team 是 read-only，paper.tex 内容 + mtime 都不变。"""
    body = "obviously some text\n"
    tex = _write_tex(tmp_path, body)
    before_content = tex.read_text(encoding="utf-8")
    before_mtime = tex.stat().st_mtime_ns

    time.sleep(0.01)
    _ = run_red_team(tex, paper_id="test")

    after_content = tex.read_text(encoding="utf-8")
    after_mtime = tex.stat().st_mtime_ns
    assert before_content == after_content
    assert before_mtime == after_mtime


# ---------------------------------------------------------------------------
# LLM evaluator hook (M-E pluggable)
# ---------------------------------------------------------------------------


def test_run_red_team_skips_llm_modes_without_evaluator(tmp_path):
    """LLM-only modes (detector_regex=None) 在没有 evaluator 时 → 静默 skip，不报错。"""
    tex = _write_tex(tmp_path, "neutral text")
    findings = run_red_team(tex, paper_id="test", evaluator=None)
    # LLM-only modes 不产 findings (None evaluator)
    llm_only_modes = {c.mode for c in CHECKS if c.detector_regex is None}
    triggered_llm_only = {f.mode for f in findings} & llm_only_modes
    assert triggered_llm_only == set()


def test_run_red_team_invokes_evaluator_for_llm_modes(tmp_path):
    """有 evaluator → LLM-only modes 调用 evaluator(mode, tex_text, paper_id)。"""
    tex = _write_tex(tmp_path, "neutral text")
    called: list[tuple[str, str]] = []

    def stub_evaluator(mode: str, tex_text: str, paper_id: str) -> list[RedTeamFinding]:
        called.append((mode, paper_id))
        # 返回 1 个 mock finding
        return [RedTeamFinding(mode=mode, severity="WARN", message=f"stub({mode})")]

    findings = run_red_team(tex, paper_id="my-paper", evaluator=stub_evaluator)
    # called 包含所有 detector_regex=None 的 mode
    called_modes = {m for m, _ in called}
    expected_llm_modes = {c.mode for c in CHECKS if c.detector_regex is None}
    assert called_modes == expected_llm_modes
    # evaluator 收到正确 paper_id
    assert all(pid == "my-paper" for _, pid in called)
    # findings 包含 evaluator 返回
    stub_findings = [f for f in findings if f.message.startswith("stub(")]
    assert len(stub_findings) == len(expected_llm_modes)


# ---------------------------------------------------------------------------
# paper-agnostic (通用化承诺)
# ---------------------------------------------------------------------------


def test_run_red_team_paper_id_param_pluggable(tmp_path):
    """paper_id 完全来自参数；不同 id 同一 tex → finding 内容一致 (algorithm paper-agnostic)。"""
    tex = _write_tex(tmp_path, "obviously the best")
    f1 = run_red_team(tex, paper_id="paper-a")
    f2 = run_red_team(tex, paper_id="paper-b")
    # 至少 1 个 finding
    assert len(f1) >= 1
    # mode / severity / message 与 paper_id 无关
    f1_summary = sorted((f.mode, f.severity, f.message) for f in f1)
    f2_summary = sorted((f.mode, f.severity, f.message) for f in f2)
    assert f1_summary == f2_summary


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "non_aphasia_cs"


def test_run_red_team_non_aphasia_cs_fixture():
    """通用化 fixture：CS paper (ANN benchmarks) 跑通 red_team 不崩。"""
    tex = _FIXTURE_ROOT / "src" / "paper.tex"
    assert tex.exists(), f"fixture missing: {tex}"
    findings = run_red_team(tex, paper_id="non_aphasia_cs")
    assert isinstance(findings, list)
    for f in findings:
        assert f.mode in DEFAULT_FAILURE_MODES


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_red_team_outputs_json(tmp_path):
    """python -m paper_agent.score.red_team --tex X --out Y → 写 JSON 含 findings。"""
    tex = _write_tex(tmp_path, "obviously trivially the best")
    out = tmp_path / "red_team.json"
    rc = red_team_cli([
        "--tex", str(tex),
        "--paper-id", "test-paper",
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["paper_id"] == "test-paper"
    assert isinstance(data["findings"], list)


def test_cli_red_team_missing_tex_returns_nonzero(tmp_path):
    rc = red_team_cli([
        "--tex", str(tmp_path / "nonexistent.tex"),
        "--paper-id", "test",
    ])
    assert rc != 0


# ---------------------------------------------------------------------------
# SAFE_REVISION_RE direct compile check
# ---------------------------------------------------------------------------


def test_safe_revision_re_is_compiled_pattern():
    assert isinstance(SAFE_REVISION_RE, re.Pattern)
