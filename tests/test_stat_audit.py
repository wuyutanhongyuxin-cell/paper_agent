"""stat_audit 单元测试 —— M-B.2 spec §D.2 stat_audit。

覆盖语义层：
  - p_value_out_of_range  ERROR  p = X 中 X ∉ [0,1]
  - anova_missing_F/df/p  WARN   ANOVA 块缺 F/df/p（任一）
  - anova_missing_eta_or_N  INFO  ANOVA 块缺 η² 或 N
  - mean_missing_sd_or_n   WARN  段含 mean/M= 但同段无 SD/N
  - ci_missing_bounds      WARN  段含 CI 但无 [lo, hi] 区间
  - LaTeX %-注释剥除
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_agent.audit.rule.stat_audit import (
    extract_p_values,
    find_anova_blocks,
    has_descriptive_stats_complete,
    has_ci_bounds,
    run_audit,
)


def _tex(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "paper.tex"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# extract_p_values
# ---------------------------------------------------------------------------

def test_extract_p_values_equals():
    """p = 0.05 形式提取。"""
    found = extract_p_values("ANOVA 结果 p = 0.05 显著。")
    assert any(v == 0.05 for _, v, _ in found)


def test_extract_p_values_less_than():
    """p < 0.001 形式提取。"""
    found = extract_p_values("p < 0.001 显著。")
    assert any(v == 0.001 for _, v, _ in found)


def test_extract_p_values_greater_than():
    """p > 0.10 形式提取。"""
    found = extract_p_values("p > 0.10 不显著。")
    assert any(v == 0.10 for _, v, _ in found)


def test_extract_p_values_scientific_notation():
    """p = 1e-5 科学计数法。"""
    found = extract_p_values("p = 1e-5 极显著。")
    assert any(abs(v - 1e-5) < 1e-9 for _, v, _ in found)


def test_extract_p_values_skips_phrases():
    """'p$<$0.05' LaTeX 数学环境也算（先剥 $）。"""
    found = extract_p_values("p$<$0.05")
    assert any(v == 0.05 for _, v, _ in found)


def test_extract_p_values_does_not_match_other_letters():
    """不应误抓 'sp = 5' / 'np = 100' 这种。"""
    found = extract_p_values("sp = 5 nope.")
    assert all(v != 5 for _, v, _ in found) or found == []


# ---------------------------------------------------------------------------
# find_anova_blocks
# ---------------------------------------------------------------------------

def test_find_anova_blocks_keyword():
    text = (
        "正常段没有相关关键词内容。\n\n"
        "ANOVA 主效应分析: F(1, 100) = 4.5, p = 0.04, η² = 0.04, N = 102.\n\n"
        "其他段。\n"
    )
    blocks = find_anova_blocks(text)
    assert len(blocks) == 1
    assert "ANOVA" in blocks[0]["text"]


def test_find_anova_blocks_F_paren_alone_triggers():
    """段含 'F(df1, df2)' 即使没写 'ANOVA' 也算 ANOVA 块。"""
    text = "主效应 F(2, 98) = 5.3, p = 0.006.\n"
    blocks = find_anova_blocks(text)
    assert len(blocks) == 1


def test_find_anova_blocks_zero():
    blocks = find_anova_blocks("这是一段普通文字内容描述, 不含相关关键字。\n")
    assert blocks == []


# ---------------------------------------------------------------------------
# has_descriptive_stats_complete
# ---------------------------------------------------------------------------

def test_has_descriptive_stats_complete_with_sd():
    """mean + SD 同段 → 完整。"""
    assert has_descriptive_stats_complete("M = 5.3, SD = 0.8, N = 20.") is True


def test_has_descriptive_stats_complete_missing_sd():
    """mean 但缺 SD → 不完整。"""
    assert has_descriptive_stats_complete("均值 M = 5.3, N = 20.") is False


def test_has_descriptive_stats_no_mean_returns_true():
    """段不含 mean → trivially 完整（无需检查）。"""
    assert has_descriptive_stats_complete("没有描述统计的段落。") is True


# ---------------------------------------------------------------------------
# has_ci_bounds
# ---------------------------------------------------------------------------

def test_has_ci_bounds_full_interval():
    assert has_ci_bounds("95% CI [0.12, 0.34].") is True


def test_has_ci_bounds_missing_interval():
    assert has_ci_bounds("95% CI 显著。") is False


def test_has_ci_bounds_no_ci_keyword_returns_true():
    """段不含 CI 关键词 → trivially 完整。"""
    assert has_ci_bounds("普通段落里没有任何区间报告字样。") is True


def test_has_ci_bounds_chinese_keyword():
    """'置信区间 [...]' 中文同样适用。"""
    assert has_ci_bounds("95% 置信区间 [0.1, 0.3]。") is True
    assert has_ci_bounds("95% 置信区间显著。") is False


# ---------------------------------------------------------------------------
# run_audit
# ---------------------------------------------------------------------------

def test_run_audit_p_out_of_range_error(tmp_path):
    """p = 1.5 → ERROR p_value_out_of_range。"""
    tex = _tex(tmp_path, "结果 p = 1.5 错误数值。\n")
    summary, findings = run_audit(tex)
    errors = [f for f in findings if f["severity"] == "ERROR" and f["rule"] == "p_value_out_of_range"]
    assert len(errors) == 1
    assert "1.5" in errors[0]["message"]


def test_run_audit_p_negative_error(tmp_path):
    """p = -0.05 → ERROR。"""
    tex = _tex(tmp_path, "p = -0.05 错。\n")
    summary, findings = run_audit(tex)
    assert any(f["rule"] == "p_value_out_of_range" for f in findings)


def test_run_audit_p_zero_one_boundary_ok(tmp_path):
    """p = 0 / p = 1 是合法边界。"""
    tex = _tex(tmp_path, "p = 0 极小, p = 1 极大都合法。\n")
    summary, findings = run_audit(tex)
    assert not any(f["rule"] == "p_value_out_of_range" for f in findings)


def test_run_audit_anova_complete_no_warn(tmp_path):
    """ANOVA 块含 F/df/p/η²/N → 0 warning。"""
    tex = _tex(tmp_path, (
        "ANOVA 词性主效应: F(1, 100) = 4.5, df = 1, "
        "p = 0.04, η² = 0.04, N = 102.\n"
    ))
    summary, findings = run_audit(tex)
    anova_warns = [f for f in findings if f["rule"].startswith("anova_")]
    assert anova_warns == []


def test_run_audit_anova_missing_p_warn(tmp_path):
    """ANOVA 块缺 p → WARN anova_missing_p。"""
    tex = _tex(tmp_path, (
        "ANOVA 词性主效应: F(1, 100) = 4.5, df = 1, η² = 0.04, N = 102.\n"
    ))
    summary, findings = run_audit(tex)
    assert any(f["rule"] == "anova_missing_p" and f["severity"] == "WARN" for f in findings)


def test_run_audit_anova_missing_eta_info(tmp_path):
    """ANOVA 块缺 η² → INFO anova_missing_eta。"""
    tex = _tex(tmp_path, (
        "ANOVA: F(1, 100) = 4.5, df = 1, p = 0.04, N = 102. 无 effect size.\n"
    ))
    summary, findings = run_audit(tex)
    assert any(
        f["rule"] == "anova_missing_eta" and f["severity"] == "INFO"
        for f in findings
    )


def test_run_audit_mean_missing_sd(tmp_path):
    """mean 出现但缺 SD/N → WARN mean_missing_sd_or_n。"""
    tex = _tex(tmp_path, "结果 M = 5.3 高于基线。\n")
    summary, findings = run_audit(tex)
    assert any(f["rule"] == "mean_missing_sd_or_n" and f["severity"] == "WARN" for f in findings)


def test_run_audit_ci_missing_bounds(tmp_path):
    """CI 出现但无 [lo, hi] → WARN ci_missing_bounds。

    注: LaTeX 中 '%' 是注释起点; 写百分号要 '\\%'.
    """
    tex = _tex(tmp_path, "95\\% CI 显著高于零。\n")
    summary, findings = run_audit(tex)
    assert any(f["rule"] == "ci_missing_bounds" and f["severity"] == "WARN" for f in findings)


def test_run_audit_p_in_comment_not_checked(tmp_path):
    """注释里的 p = 5.0（非法）不该报错。"""
    tex = _tex(tmp_path, "% p = 5.0 commented away\n正文无统计错误。\n")
    summary, findings = run_audit(tex)
    assert not any(f["rule"] == "p_value_out_of_range" for f in findings)


def test_run_audit_clean_paper(tmp_path):
    """完全合规的段 → 0 findings。"""
    tex = _tex(tmp_path, (
        "ANOVA 主效应: F(1, 100) = 4.5, df = 1, p = 0.04, "
        "η² = 0.04, N = 102, 95% CI [0.01, 0.08].\n"
        "描述统计: M = 5.3, SD = 0.8, N = 102.\n"
    ))
    summary, findings = run_audit(tex)
    errors = [f for f in findings if f["severity"] == "ERROR"]
    warns = [f for f in findings if f["severity"] == "WARN"]
    assert errors == []
    assert warns == []


def test_run_audit_summary_fields(tmp_path):
    tex = _tex(tmp_path, (
        "ANOVA: F(1, 100) = 4.5, p = 0.04.\n"
    ))
    summary, _ = run_audit(tex)
    assert "anova_block_count" in summary
    assert "p_value_count" in summary
