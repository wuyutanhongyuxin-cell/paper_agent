"""`paper-agent new` scaffold 子命令 e2e — 严格解决"起新论文要手抄模板"盲点。

spec §A.3 第五原则：paper-agent 必须跨学科 / 跨语言可消费。0.1.0/0.1.0.post2 的
`init` 只生成构建链 (.latexmkrc + compile.ps1)，论文源 (paper.tex / references.bib)
要用户手抄；这一缺口让 [[feedback_paper_agent_long_term_generality]] 通用化承诺
缺一块兜底。`new` 子命令在 init 之上加一层 jinja2 模板生成，把"起新论文"从手抄
退化为一行 CLI 调用。

测试覆盖：
  - 中英文模板各自能生成
  - 拒绝覆盖既有 paper.tex / references.bib（feedback_no_overwrite_source 硬约束）
  - 生成的骨架跑 audit 应 0 findings 0 ERROR（模板自身合规）
  - 生成的骨架 audit 仍是 read-only（L-033 sha256 不变）
"""
import hashlib
import subprocess
import sys
from pathlib import Path


def _run_new(work, lang, field, paper_name="paper"):
    return subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "new", str(work),
         "--lang", lang, "--field", field, "--paper-name", paper_name],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _run_audit(work, lang):
    return subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit", str(work),
         "--lang", lang],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_new_zh_creates_full_skeleton(tmp_path):
    """zh + cs：4 个文件全生成。"""
    work = tmp_path / "fresh_zh_cs"
    result = _run_new(work, "zh", "cs")
    assert result.returncode == 0, (
        f"new failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert (work / "src" / "paper.tex").exists()
    assert (work / "src" / "references.bib").exists()
    assert (work / ".latexmkrc").exists()
    assert (work / "compile.ps1").exists()


def test_new_en_creates_full_skeleton(tmp_path):
    """en + sciences：4 个文件全生成，paper.tex 用 article 文档类。"""
    work = tmp_path / "fresh_en_sci"
    result = _run_new(work, "en", "sciences")
    assert result.returncode == 0, (
        f"new failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    paper_tex = (work / "src" / "paper.tex").read_text(encoding="utf-8")
    assert r"\documentclass[11pt,a4paper]{article}" in paper_tex, (
        f"en template should use article class, got:\n{paper_tex[:200]}"
    )
    assert (work / "src" / "references.bib").exists()
    assert (work / ".latexmkrc").exists()
    assert (work / "compile.ps1").exists()


def test_new_zh_uses_ctexart(tmp_path):
    """zh 模板必须用 ctexart 文档类 + fontset=fandol（跨平台 CI 友好）。"""
    work = tmp_path / "fresh_zh_check"
    result = _run_new(work, "zh", "linguistics")
    assert result.returncode == 0
    paper_tex = (work / "src" / "paper.tex").read_text(encoding="utf-8")
    assert r"\documentclass[zihao=-4,UTF8,fontset=fandol]{ctexart}" in paper_tex, (
        f"zh template should use ctexart + fandol, got:\n{paper_tex[:200]}"
    )


def test_new_refuses_overwrite_existing_paper_tex(tmp_path):
    """已存在 paper.tex 时 refuse 覆盖（feedback_no_overwrite_source 硬约束）。"""
    work = tmp_path / "has_paper"
    src = work / "src"
    src.mkdir(parents=True)
    paper_tex = src / "paper.tex"
    existing = "% user's existing draft do not touch\n\\documentclass{article}\n"
    paper_tex.write_text(existing, encoding="utf-8")

    result = _run_new(work, "zh", "cs")
    assert result.returncode == 1, (
        f"new should refuse to overwrite, but rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    assert "refuse to overwrite" in result.stderr.lower() or "scaffolderror" in result.stderr.lower()
    # critical: existing paper.tex must be untouched byte-for-byte
    assert paper_tex.read_text(encoding="utf-8") == existing


def test_new_refuses_overwrite_existing_references_bib(tmp_path):
    """已存在 references.bib 时 refuse 覆盖（feedback_no_overwrite_source 硬约束）。"""
    work = tmp_path / "has_bib"
    src = work / "src"
    src.mkdir(parents=True)
    bib = src / "references.bib"
    existing = "% user's real bibliography do not touch\n@misc{real, year={2026}}\n"
    bib.write_text(existing, encoding="utf-8")

    result = _run_new(work, "zh", "cs")
    assert result.returncode == 1
    assert bib.read_text(encoding="utf-8") == existing


def test_new_zh_then_audit_zero_findings(tmp_path):
    """zh 骨架跑 audit 必须 0 findings 0 ERROR — 模板自身得通过自家审计。"""
    work = tmp_path / "scaffold_zh_audit"
    new_result = _run_new(work, "zh", "linguistics")
    assert new_result.returncode == 0, new_result.stderr

    audit_result = _run_audit(work, "zh")
    assert audit_result.returncode == 0, (
        f"audit failed on fresh zh scaffold: rc={audit_result.returncode}\n"
        f"stdout={audit_result.stdout}\nstderr={audit_result.stderr}"
    )
    assert "0 findings (0 ERROR)" in audit_result.stdout, (
        f"zh scaffold should be fully clean; got:\n{audit_result.stdout}"
    )


def test_new_en_then_audit_zero_findings(tmp_path):
    """en 骨架跑 audit (lang=en) 必须 0 findings 0 ERROR。

    Note: en rules dict is currently empty (0.2.0+ placeholder), so en audit
    is effectively bib_audit + structural punct (P8/P9) + structural humanize
    (R4-R7). Our en template must still pass those.
    """
    work = tmp_path / "scaffold_en_audit"
    new_result = _run_new(work, "en", "cs")
    assert new_result.returncode == 0, new_result.stderr

    audit_result = _run_audit(work, "en")
    assert audit_result.returncode == 0, audit_result.stderr
    assert "0 findings (0 ERROR)" in audit_result.stdout, (
        f"en scaffold should be fully clean; got:\n{audit_result.stdout}"
    )


def test_new_audit_is_read_only(tmp_path):
    """L-033 硬约束：scaffold 生成后跑 audit 不能动 paper.tex 字节。"""
    work = tmp_path / "scaffold_l033"
    _run_new(work, "zh", "cs")
    paper_tex = work / "src" / "paper.tex"
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    audit_result = _run_audit(work, "zh")
    assert audit_result.returncode == 0

    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_before == sha_after, (
        "audit 修改了 scaffold 出的 paper.tex 字节 — 违反 L-033 唯一写入路径"
    )


def test_new_ja_unsupported_returns_clear_error(tmp_path):
    """ja 等不支持的 lang 必须明确报错，不静默回退。"""
    work = tmp_path / "fresh_ja"
    # argparse choices=["zh", "en"] should reject "ja" before reaching scaffold
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "new", str(work),
         "--lang", "ja", "--field", "cs"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode != 0
    assert "ja" in result.stderr or "invalid choice" in result.stderr.lower()
