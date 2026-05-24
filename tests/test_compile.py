"""Compile module: template rendering + smoke (latexmk optional)。"""
import shutil
from pathlib import Path

import pytest


def test_render_latexmkrc_contains_required_lines(tmp_path):
    from paper_agent.compile.latexmkrc_gen import render_latexmkrc

    rendered = render_latexmkrc(tmp_path / "p", rules="bib,punct,humanize")
    assert "$pdf_mode = 5" in rendered
    assert "%O %S" in rendered  # %O 自动注入 -no-pdf
    assert "pre_compile_hook" in rendered
    assert "paper-agent" in rendered  # audit-gate 注入


def test_render_compile_ps1_contains_required_lines(tmp_path):
    from paper_agent.compile.compile_ps1 import render_compile_ps1

    paper_root = tmp_path / "p"
    rendered = render_compile_ps1(paper_root, paper_name="paper")
    assert "latexmk" in rendered
    assert "UTF8" in rendered  # Console.OutputEncoding 设置
    assert "chcp 65001" in rendered  # cp936 兜底
    # paper_root 注入 + Tex 路径模板正确（$Src 是 PowerShell 变量，不在渲染时展开）
    assert str(paper_root) in rendered
    assert '$Tex  = "$Src\\paper.tex"' in rendered


def test_write_latexmkrc_creates_file(tmp_path):
    from paper_agent.compile.latexmkrc_gen import write_latexmkrc

    out = write_latexmkrc(tmp_path)
    assert out.exists()
    assert out.name == ".latexmkrc"
    assert "$pdf_mode = 5" in out.read_text(encoding="utf-8")


def test_write_compile_ps1_creates_file(tmp_path):
    from paper_agent.compile.compile_ps1 import write_compile_ps1

    out = write_compile_ps1(tmp_path, paper_name="paper")
    assert out.exists()
    assert out.name == "compile.ps1"
    txt = out.read_text(encoding="utf-8")
    assert "latexmk" in txt
    assert "chcp 65001" in txt


def test_run_compile_raises_without_latexmkrc(tmp_path):
    """run_compile 在缺 .latexmkrc 时立即抛 RuntimeError（init 前置）。"""
    from paper_agent.compile.compile_ps1 import run_compile

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "paper.tex").write_text("x", encoding="utf-8")

    # 若有 latexmk 才能 reach .latexmkrc 检查；否则先抛 "latexmk not in PATH"
    if shutil.which("latexmk") is None:
        with pytest.raises(RuntimeError, match="latexmk not in PATH"):
            run_compile(tmp_path)
    else:
        with pytest.raises(RuntimeError, match=".latexmkrc not found"):
            run_compile(tmp_path)


@pytest.mark.skipif(shutil.which("latexmk") is None, reason="latexmk not installed")
def test_run_compile_smoke_minimal_tex(tmp_path):
    """有 latexmk 时跑最小 tex；无则 skip。"""
    from paper_agent.compile.latexmkrc_gen import write_latexmkrc
    from paper_agent.compile.compile_ps1 import run_compile

    paper_root = tmp_path / "p"
    (paper_root / "src").mkdir(parents=True)
    (paper_root / "src" / "paper.tex").write_text(
        r"\documentclass{article}\begin{document}Hello\end{document}",
        encoding="utf-8",
    )
    write_latexmkrc(paper_root, rules="")  # 空 rules 防 audit-gate 失败
    code = run_compile(paper_root)
    assert code == 0 or code == 1  # MiKTeX update-check 可能返 1
    assert (paper_root / "out" / "paper.pdf").exists()
