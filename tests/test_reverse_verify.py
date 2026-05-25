"""reverse_verify (number rule) 单元测试 —— M-A reverse_verify 通用化抽出。

覆盖语义层：
  - all hit → 0 findings
  - one miss → 1 ERROR finding (默认 severity)
  - severity override (WARN / INFO)
  - 多 candidate 任一命中即 hit
  - LaTeX %-注释里的数字不算 hit（与 number_audit.py 等价）
  - \\% 转义百分号保留（不当注释剥）
  - schema 错误 → ValueError
  - lang=en 字面候选不影响匹配
"""
import json
from pathlib import Path

import pytest

from paper_agent.audit.rule.reverse_verify import (
    load_truth,
    strip_tex_comments,
    run_audit,
)


def _write(p: Path, content: str) -> Path:
    p.write_text(content, encoding="utf-8")
    return p


def _truth(tmp_path: Path, items: list[dict], **extra) -> Path:
    obj = {"version": "0.1.1", "items": items, **extra}
    p = tmp_path / "truth.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _tex(tmp_path: Path, body: str) -> Path:
    return _write(tmp_path / "paper.tex", body)


# ---------------------------------------------------------------------------
# strip_tex_comments
# ---------------------------------------------------------------------------

def test_strip_tex_comments_removes_inline():
    src = "数字 1234 OK\n这行 % 1234 是注释\n"
    assert "1234" in strip_tex_comments(src).splitlines()[0]
    assert "1234" not in strip_tex_comments(src).splitlines()[1]


def test_strip_tex_comments_preserves_escaped_percent():
    """\\% 是字面百分号，不当注释起点。"""
    src = "覆盖率 85\\% (340/400)\n"
    out = strip_tex_comments(src)
    assert "85" in out
    assert "(340/400)" in out  # 不能被截掉


def test_strip_tex_comments_preserves_line_count():
    """行数保留（splitlines() 元素数；trailing \\n 在 splitlines+join 后丢失是
    Python str 标准行为，与 number_audit.py 等价；行号定位不受影响）。"""
    src = "a\n% b\nc\n"
    out = strip_tex_comments(src)
    assert len(out.splitlines()) == len(src.splitlines())


# ---------------------------------------------------------------------------
# load_truth schema validation
# ---------------------------------------------------------------------------

def test_load_truth_valid_minimal(tmp_path):
    t = _truth(tmp_path, [{"name": "foo", "candidates": ["bar"]}])
    data = load_truth(t)
    assert data["items"][0]["name"] == "foo"


def test_load_truth_missing_items(tmp_path):
    p = tmp_path / "truth.json"
    p.write_text('{"version": "0.1.1"}', encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'items'"):
        load_truth(p)


def test_load_truth_empty_candidates(tmp_path):
    t = _truth(tmp_path, [{"name": "foo", "candidates": []}])
    with pytest.raises(ValueError, match="missing 'candidates'"):
        load_truth(t)


def test_load_truth_empty_name(tmp_path):
    t = _truth(tmp_path, [{"name": "", "candidates": ["bar"]}])
    with pytest.raises(ValueError, match="missing 'name'"):
        load_truth(t)


def test_load_truth_invalid_severity(tmp_path):
    t = _truth(tmp_path, [{"name": "foo", "candidates": ["bar"], "severity": "FATAL"}])
    with pytest.raises(ValueError, match="severity="):
        load_truth(t)


def test_load_truth_nonexistent_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_truth(tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# run_audit core semantics
# ---------------------------------------------------------------------------

def test_run_audit_all_hit_returns_zero_findings(tmp_path):
    tex = _tex(tmp_path, "BCC 原始词数 1,818,649\nANOVA p = 0.7287\n")
    truth = _truth(tmp_path, [
        {"name": "BCC 原始词数", "candidates": ["1,818,649", "1818649"]},
        {"name": "ANOVA p", "candidates": ["0.7287"]},
    ])
    summary, findings = run_audit(tex, truth)
    assert summary["hit"] == 2
    assert summary["miss"] == 0
    assert findings == []


def test_run_audit_one_miss_returns_one_error(tmp_path):
    tex = _tex(tmp_path, "BCC 1,818,649 OK\n")
    truth = _truth(tmp_path, [
        {"name": "BCC 原始词数", "candidates": ["1,818,649"]},
        {"name": "缺失真值", "candidates": ["404"]},
    ])
    summary, findings = run_audit(tex, truth)
    assert summary["hit"] == 1
    assert summary["miss"] == 1
    assert len(findings) == 1
    f = findings[0]
    assert f["severity"] == "ERROR"
    assert f["rule"] == "number_miss"
    assert f["name"] == "缺失真值"
    assert "404" in f["message"]


def test_run_audit_severity_override(tmp_path):
    tex = _tex(tmp_path, "正文里没这个数。\n")
    truth = _truth(tmp_path, [
        {"name": "可选指标", "candidates": ["999"], "severity": "WARN"},
    ])
    summary, findings = run_audit(tex, truth)
    assert findings[0]["severity"] == "WARN"


def test_run_audit_any_candidate_hits(tmp_path):
    """多 candidate 任一命中即 hit（覆盖千分位 / LaTeX 转义形式）。"""
    tex = _tex(tmp_path, "BCC 1{,}818{,}649 LaTeX-form\n")
    truth = _truth(tmp_path, [
        {"name": "BCC", "candidates": ["1,818,649", "1818649", "1{,}818{,}649"]},
    ])
    summary, findings = run_audit(tex, truth)
    assert summary["miss"] == 0


def test_run_audit_number_in_comment_not_hit(tmp_path):
    """LaTeX 注释里的数字不算 hit。"""
    tex = _tex(tmp_path, "正文无数字。\n% 这里有 1,818,649 但是被注释了\n")
    truth = _truth(tmp_path, [
        {"name": "BCC", "candidates": ["1,818,649"]},
    ])
    summary, findings = run_audit(tex, truth)
    assert summary["miss"] == 1


def test_run_audit_escaped_percent_kept(tmp_path):
    """\\% 后的内容不当注释剥；覆盖率写作 85\\% (340/400) 仍能命中 340/400。"""
    tex = _tex(tmp_path, "AoA 覆盖率 85\\% (340/400)\n")
    truth = _truth(tmp_path, [
        {"name": "AoA 覆盖率", "candidates": ["340/400"]},
    ])
    summary, findings = run_audit(tex, truth)
    assert summary["miss"] == 0


def test_run_audit_section_in_message(tmp_path):
    tex = _tex(tmp_path, "正文。\n")
    truth = _truth(tmp_path, [
        {"name": "X", "section": "3.1 词频", "candidates": ["999"]},
    ])
    _, findings = run_audit(tex, truth)
    assert "§3.1 词频" in findings[0]["message"]


def test_run_audit_lang_independent(tmp_path):
    """候选字符串是字面字面量，lang 参数不影响匹配。"""
    tex = _tex(tmp_path, "value = 42.\n")
    truth = _truth(tmp_path, [{"name": "v", "candidates": ["42"]}])
    summary, _ = run_audit(tex, truth)
    assert summary["miss"] == 0


def test_run_audit_returns_paper_metadata(tmp_path):
    tex = _tex(tmp_path, "x")
    truth = _truth(
        tmp_path,
        [{"name": "y", "candidates": ["404"]}],
        paper={"id": "test-paper", "title": "T"},
    )
    summary, _ = run_audit(tex, truth)
    assert summary["paper"] == {"id": "test-paper", "title": "T"}
    assert summary["truth_version"] == "0.1.1"
