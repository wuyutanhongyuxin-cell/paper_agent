"""fig_audit (figure rule) 单元测试 —— M-B.1 spec §D.2 fig_audit。

覆盖语义层：
  - \\label uniqueness（figure 环境内）：重复 → ERROR
  - \\caption ≥ 20 chars：过短 → WARN
  - \\label 反向覆盖：figure 内的 fig:X 必须被 \\ref/\\autoref/\\cref 引用 → WARN
  - figure* 环境同样适用
  - LaTeX %-注释里的 \\label / \\ref 不参与判定
  - 通用化：rule 不 hardcode 学科特异 label naming
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_agent.audit.rule.fig_audit import (
    extract_caption,
    extract_labels,
    find_figure_envs,
    find_ref_keys,
    run_audit,
    strip_tex_comments,
)


def _tex(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "paper.tex"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_strip_tex_comments_basic():
    src = "\\label{fig:a} OK\n% \\label{fig:b} commented\n"
    out = strip_tex_comments(src)
    assert "fig:a" in out
    assert "fig:b" not in out


def test_find_figure_envs_single():
    tex = "\\begin{figure}\n\\caption{C}\n\\label{fig:x}\n\\end{figure}\n"
    envs = find_figure_envs(tex)
    assert len(envs) == 1
    assert "\\label{fig:x}" in envs[0]["body"]


def test_find_figure_envs_star():
    """figure* 双栏环境也算 figure 环境。"""
    tex = "\\begin{figure*}\n\\label{fig:wide}\n\\caption{Wide caption text 20+ chars}\n\\end{figure*}\n"
    envs = find_figure_envs(tex)
    assert len(envs) == 1


def test_find_figure_envs_multiple():
    tex = (
        "\\begin{figure}\n\\label{fig:a}\\caption{Caption A is long enough.}\n\\end{figure}\n"
        "text\n"
        "\\begin{figure}\n\\label{fig:b}\\caption{Caption B is long enough.}\n\\end{figure}\n"
    )
    envs = find_figure_envs(tex)
    assert len(envs) == 2


def test_extract_labels_from_env():
    body = "\\caption{X}\n\\label{fig:a}\n\\label{fig:b}\n"
    labels = extract_labels(body)
    assert labels == ["fig:a", "fig:b"]


def test_extract_caption_from_env():
    body = "\\caption{Hello world figure}\n\\label{fig:x}\n"
    cap = extract_caption(body)
    assert cap == "Hello world figure"


def test_extract_caption_balanced_braces():
    """\\caption{...} 内含嵌套花括号也要正确剥出。"""
    body = "\\caption{Plot of $f(x) = \\frac{1}{x}$ over $[0, 1]$}\n"
    cap = extract_caption(body)
    assert "frac" in cap
    assert "[0, 1]" in cap


def test_extract_caption_optional_short():
    """\\caption[short]{long} 取 long 不取 short（learn from APA）。"""
    body = "\\caption[short]{This is the long caption text}\n"
    cap = extract_caption(body)
    assert cap == "This is the long caption text"


def test_find_ref_keys_multiple_commands():
    """\\ref / \\autoref / \\cref / \\Cref / \\Vref 都算引用。"""
    tex = (
        "见 \\ref{fig:a}, \\autoref{fig:b}, "
        "\\cref{fig:c}, \\Cref{fig:d}, \\Vref{fig:e}."
    )
    refs = find_ref_keys(tex)
    assert {"fig:a", "fig:b", "fig:c", "fig:d", "fig:e"} <= refs


def test_find_ref_keys_multi_in_cref():
    """\\cref{a,b,c} 多 key 也要拆。"""
    tex = "\\cref{fig:a, fig:b, fig:c}"
    refs = find_ref_keys(tex)
    assert {"fig:a", "fig:b", "fig:c"} <= refs


# ---------------------------------------------------------------------------
# run_audit core
# ---------------------------------------------------------------------------

def test_run_audit_all_clean(tmp_path):
    """合规 figure：label 唯一 + caption ≥ 20 + 被 ref 引用 → 0 findings。"""
    tex = _tex(tmp_path, (
        "\\begin{figure}\n"
        "\\includegraphics{img.pdf}\n"
        "\\caption{This caption is long enough to satisfy the 20 char rule.}\n"
        "\\label{fig:x}\n"
        "\\end{figure}\n"
        "正文里见图 \\ref{fig:x}。\n"
    ))
    summary, findings = run_audit(tex)
    assert summary["figure_count"] == 1
    assert findings == []


def test_run_audit_duplicate_label_error(tmp_path):
    """两个 figure 里出现相同 \\label{fig:x} → ERROR label_duplicate。"""
    tex = _tex(tmp_path, (
        "\\begin{figure}\n"
        "\\caption{Caption number one long enough text here}\n"
        "\\label{fig:x}\n"
        "\\end{figure}\n"
        "\\begin{figure}\n"
        "\\caption{Caption number two long enough text here}\n"
        "\\label{fig:x}\n"
        "\\end{figure}\n"
        "\\ref{fig:x}\n"
    ))
    summary, findings = run_audit(tex)
    errors = [f for f in findings if f["severity"] == "ERROR" and f["rule"] == "label_duplicate"]
    assert len(errors) == 1
    assert "fig:x" in errors[0]["message"]


def test_run_audit_caption_too_short(tmp_path):
    """caption 字符数 < 20 → WARN caption_too_short。"""
    tex = _tex(tmp_path, (
        "\\begin{figure}\n"
        "\\caption{Short cap}\n"
        "\\label{fig:s}\n"
        "\\end{figure}\n"
        "\\ref{fig:s}\n"
    ))
    summary, findings = run_audit(tex)
    warns = [f for f in findings if f["rule"] == "caption_too_short"]
    assert len(warns) == 1
    assert warns[0]["severity"] == "WARN"
    assert "Short cap" in warns[0]["message"]


def test_run_audit_orphan_figure(tmp_path):
    """figure 内 \\label{fig:x} 但正文无 \\ref{fig:x} → WARN orphan_figure。"""
    tex = _tex(tmp_path, (
        "\\begin{figure}\n"
        "\\caption{This caption is intentionally long enough.}\n"
        "\\label{fig:lonely}\n"
        "\\end{figure}\n"
        "正文里没有引用任何图。\n"
    ))
    summary, findings = run_audit(tex)
    orphans = [f for f in findings if f["rule"] == "orphan_figure"]
    assert len(orphans) == 1
    assert orphans[0]["severity"] == "WARN"
    assert "fig:lonely" in orphans[0]["message"]


def test_run_audit_ref_in_comment_does_not_count(tmp_path):
    """注释里的 \\ref 不能"救活"orphan figure。"""
    tex = _tex(tmp_path, (
        "\\begin{figure}\n"
        "\\caption{This caption is long enough for the rule.}\n"
        "\\label{fig:x}\n"
        "\\end{figure}\n"
        "% \\ref{fig:x} 这是注释\n"
    ))
    summary, findings = run_audit(tex)
    assert any(f["rule"] == "orphan_figure" for f in findings)


def test_run_audit_figure_star_supported(tmp_path):
    """figure* 双栏 figure 也走同套规则。"""
    tex = _tex(tmp_path, (
        "\\begin{figure*}\n"
        "\\caption{Wide caption long enough definitely.}\n"
        "\\label{fig:wide}\n"
        "\\end{figure*}\n"
        "\\ref{fig:wide}\n"
    ))
    summary, findings = run_audit(tex)
    assert summary["figure_count"] == 1
    assert findings == []


def test_run_audit_zero_figures(tmp_path):
    """没 figure 环境 → 0 findings + summary.figure_count=0。"""
    tex = _tex(tmp_path, "正文什么图都没有。\n")
    summary, findings = run_audit(tex)
    assert summary["figure_count"] == 0
    assert findings == []


def test_run_audit_chinese_caption_charcount(tmp_path):
    """中文 caption 按 char 数：'图一二三四五六七八九十一二三四五六七八九' = 20 字 → 通过."""
    tex = _tex(tmp_path, (
        "\\begin{figure}\n"
        "\\caption{图一二三四五六七八九十一二三四五六七八九二十}\n"
        "\\label{fig:cn}\n"
        "\\end{figure}\n"
        "\\ref{fig:cn}\n"
    ))
    summary, findings = run_audit(tex)
    assert not any(f["rule"] == "caption_too_short" for f in findings)


def test_run_audit_caption_missing(tmp_path):
    """figure 内根本没 \\caption → caption_too_short 也算（长度 0）。"""
    tex = _tex(tmp_path, (
        "\\begin{figure}\n"
        "\\label{fig:nocap}\n"
        "\\end{figure}\n"
        "\\ref{fig:nocap}\n"
    ))
    summary, findings = run_audit(tex)
    assert any(f["rule"] == "caption_too_short" for f in findings)


def test_run_audit_label_outside_figure_env_not_checked(tmp_path):
    """\\label 出现在 figure 环境外（如 section）不参与 fig_audit。"""
    tex = _tex(tmp_path, (
        "\\section{Intro}\\label{sec:intro}\n"
        "\\begin{figure}\n"
        "\\caption{This caption is long enough for the rule.}\n"
        "\\label{fig:x}\n"
        "\\end{figure}\n"
        "\\ref{fig:x}\n"
    ))
    summary, findings = run_audit(tex)
    # sec:intro 不应该被检测，只看 fig:x
    assert findings == []


def test_run_audit_returns_summary_keys(tmp_path):
    tex = _tex(tmp_path, (
        "\\begin{figure}\n\\caption{Long enough caption text here.}\n"
        "\\label{fig:a}\n\\end{figure}\n\\ref{fig:a}\n"
    ))
    summary, _ = run_audit(tex)
    assert "figure_count" in summary
    assert "label_count" in summary
    assert "ref_count" in summary
