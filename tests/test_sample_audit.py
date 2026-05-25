"""sample_audit 单元测试 —— M-B.3 spec §D.2 sample_audit。

覆盖语义层：
  - 随机抽 N 段 → 生成 N 个 INFO finding
  - --seed 可重现性
  - paragraph 定义：空行分隔的非空文本块
  - 跳过 figure/table/equation 环境内段落
  - 跳过 \\section/\\subsection 标题行
  - 跳过过短段（< MIN_PARAGRAPH_CHARS）
  - N > 可抽段数 → 抽到可抽的全部，不报错
  - LaTeX %-注释剥除
  - findings 全部 INFO 级别（rc 不阻断）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_agent.audit.rule.sample_audit import (
    extract_paragraphs,
    run_audit,
)


def _tex(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "paper.tex"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# extract_paragraphs
# ---------------------------------------------------------------------------

def test_extract_paragraphs_blank_line_separated():
    tex = (
        "第一段：研究背景，长度足够长用于人工复核测试，需要至少 50 字符达到阈值条件成立。\n\n"
        "第二段：方法描述，详细说明实验设计与数据采集流程的过程，超过最小段长阈值。\n\n"
        "第三段：结果讨论，统计推断与可信区间报告的完整规范叙述符合学术报告规范。\n"
    )
    paras = extract_paragraphs(tex)
    assert len(paras) == 3
    assert "研究背景" in paras[0]["text"]


def test_extract_paragraphs_skips_short():
    tex = (
        "短。\n\n"
        "这一段足够长，用于通过最小长度阈值，模拟实际正文段落，含 50 字符以上。\n\n"
        "短\n"
    )
    paras = extract_paragraphs(tex)
    assert len(paras) == 1


def test_extract_paragraphs_skips_section_headings():
    tex = (
        "\\section{引言}\n\n"
        "正文一段，足够长以通过过滤阈值，描述研究背景与动机，含五十字符以上。\n\n"
        "\\subsection{小节}\n\n"
        "正文二段，同样足够长以通过过滤阈值，含五十字符以上的有效内容。\n"
    )
    paras = extract_paragraphs(tex)
    # 不应该抽到 \section/\subsection 那两段
    for p in paras:
        assert not p["text"].lstrip().startswith("\\section")
        assert not p["text"].lstrip().startswith("\\subsection")
    assert len(paras) == 2


def test_extract_paragraphs_skips_environments():
    """figure/table/equation/align/itemize 环境内的不算 paragraph。"""
    tex = (
        "正文一段，足够长以通过过滤阈值，描述研究背景与动机说明，含五十字符以上。\n\n"
        "\\begin{figure}\n"
        "\\includegraphics{img.pdf}\n"
        "\\caption{这是 caption 内容用于环境过滤测试需要超过阈值长度有效。}\n"
        "\\end{figure}\n\n"
        "正文二段，同样足够长以通过过滤阈值，描述方法细节与实验过程，超过阈值。\n"
    )
    paras = extract_paragraphs(tex)
    # 只应该有两段正文，figure block 整体不能算
    assert len(paras) == 2
    for p in paras:
        assert "begin{figure}" not in p["text"]
        assert "caption" not in p["text"]


def test_extract_paragraphs_comments_stripped():
    tex = (
        "% 全行注释段，不算\n\n"
        "正文段，足够长以通过过滤阈值描述研究内容与实验过程详尽，超过五十字符。\n"
    )
    paras = extract_paragraphs(tex)
    assert len(paras) == 1
    assert "全行注释" not in paras[0]["text"]


def test_extract_paragraphs_line_numbers():
    """每段返回起始行号。"""
    tex = (
        "L1 第一段足够长以通过过滤阈值描述研究背景与动机说明含五十字符以上内容。\n\n"
        "L3 第二段同样足够长以通过过滤阈值描述方法细节与实验过程超过最小阈值。\n"
    )
    paras = extract_paragraphs(tex)
    assert paras[0]["line"] == 1
    assert paras[1]["line"] == 3


# ---------------------------------------------------------------------------
# run_audit
# ---------------------------------------------------------------------------

def test_run_audit_seed_reproducible(tmp_path):
    """同一 seed → 抽出同样的段。"""
    paras_text = "\n\n".join(
        f"段落 {i:02d} 内容足够长以通过过滤阈值描述某项研究内容含有意义五十字符以上。"
        for i in range(10)
    )
    tex = _tex(tmp_path, paras_text + "\n")
    summary_a, findings_a = run_audit(tex, n=3, seed=42)
    summary_b, findings_b = run_audit(tex, n=3, seed=42)
    sampled_a = [f["paragraph_text"] for f in findings_a]
    sampled_b = [f["paragraph_text"] for f in findings_b]
    assert sampled_a == sampled_b


def test_run_audit_seed_different_different_sample(tmp_path):
    """不同 seed → 大概率抽不同段（弱断言：至少有一段不同）。"""
    paras_text = "\n\n".join(
        f"段落 {i:02d} 内容足够长以通过过滤阈值描述某项研究内容含有意义五十字符以上。"
        for i in range(10)
    )
    tex = _tex(tmp_path, paras_text + "\n")
    _, findings_a = run_audit(tex, n=3, seed=1)
    _, findings_b = run_audit(tex, n=3, seed=2)
    sampled_a = set(f["paragraph_text"] for f in findings_a)
    sampled_b = set(f["paragraph_text"] for f in findings_b)
    assert sampled_a != sampled_b


def test_run_audit_returns_n_findings(tmp_path):
    """N=3 → 3 个 finding（所有 INFO 级别）。"""
    paras_text = "\n\n".join(
        f"段落 {i:02d} 内容足够长以通过过滤阈值描述某项研究内容含有意义五十字符以上。"
        for i in range(10)
    )
    tex = _tex(tmp_path, paras_text + "\n")
    summary, findings = run_audit(tex, n=3, seed=42)
    assert len(findings) == 3
    for f in findings:
        assert f["severity"] == "INFO"
        assert f["rule"] == "sample_review"


def test_run_audit_n_greater_than_available(tmp_path):
    """N > 可抽段数 → 抽到可抽的全部，不报错。"""
    tex = _tex(tmp_path, (
        "只有一段够长正文段落用于人工复核测试足够长度超过五十字符达到阈值条件。\n"
    ))
    summary, findings = run_audit(tex, n=10, seed=42)
    assert len(findings) <= 1


def test_run_audit_zero_paragraphs(tmp_path):
    """没有可抽段 → 0 finding + 不崩。"""
    tex = _tex(tmp_path, "短\n\n短\n")
    summary, findings = run_audit(tex, n=3, seed=42)
    assert findings == []


def test_run_audit_finding_has_review_prompt(tmp_path):
    """每个 finding 含 paper-agnostic 复核 prompt 模板。"""
    tex = _tex(tmp_path, (
        "正文段足够长以通过过滤阈值描述研究内容含有意义内容超过五十字符达到阈值。\n"
    ))
    summary, findings = run_audit(tex, n=1, seed=42)
    assert len(findings) == 1
    msg = findings[0]["message"]
    # paper-agnostic 模板应该提到通用复核维度
    assert "事实" in msg or "事实准确" in msg
    assert "语言" in msg or "流畅" in msg or "AI" in msg
    assert "上下文" in msg or "连贯" in msg


def test_run_audit_prompt_not_hardcoded_field(tmp_path):
    """通用化：prompt 不应该 hardcode 学科特异术语（如 BCC / ANOVA / 词频等）。"""
    tex = _tex(tmp_path, (
        "正文段足够长以通过过滤阈值描述研究内容含有意义内容超过五十字符达到阈值。\n"
    ))
    summary, findings = run_audit(tex, n=1, seed=42)
    msg = findings[0]["message"]
    # 不能 hardcode 任何学科特异 token
    forbidden = ["BCC", "ANOVA", "失语症", "词频", "MMS", "Whisper"]
    for tok in forbidden:
        assert tok not in msg, f"prompt 不应 hardcode 学科特异 token '{tok}'"


def test_run_audit_summary_fields(tmp_path):
    tex = _tex(tmp_path, (
        "正文段一足够长以通过过滤阈值描述研究内容含有意义内容超过五十字符达到阈值。\n\n"
        "正文段二足够长以通过过滤阈值描述研究内容含有意义内容超过五十字符达到阈值。\n"
    ))
    summary, _ = run_audit(tex, n=1, seed=42)
    assert summary["sampled"] == 1
    assert summary["paragraph_pool"] == 2
    assert summary["seed"] == 42
