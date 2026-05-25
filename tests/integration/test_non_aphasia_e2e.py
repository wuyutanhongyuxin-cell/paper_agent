"""非失语症 e2e fixture — paper-agent 跨学科通用化承诺的回归保护。

spec §A.3 第五原则：paper-agent 必须跨学科可消费，不依赖 linguistics-specific 假设。
fixture 选 cs 领域（k-NN ANN 算法 HNSW vs IVF-PQ 实证比较），与失语症 / 词汇研究 / 维吾尔语
无任何关联。fixture 设计成完全干净（0 findings / 0 ERROR），任何回归（如规则被偷换成
linguistics-only）都会暴露为新增 finding 或 ERROR。

补 [[feedback_paper_agent_long_term_generality]] 长期通用化目标的 e2e 证据缺口：
0.1.0 之前 5 个 min_*.tex 仅覆盖**单元**违例 fixture，端到端只有失语症 paper。
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "non_aphasia_cs"


def test_fixture_present():
    assert (FIXTURE / "src" / "paper.tex").exists()
    assert (FIXTURE / "src" / "references.bib").exists()


def test_audit_zero_findings(tmp_path):
    """cs paper 跑 audit 全链路应 0 findings 0 ERROR。

    fixture 设计为完全干净 — R1/R2/P1-P9/bib 全过。任何输出 finding 都说明
    (a) 规则误报（被 cs 文本词汇误命中），或 (b) 规则真的找到一个该 paper 的写作问题。
    """
    work = tmp_path / "non_aphasia_cs"
    shutil.copytree(FIXTURE, work)

    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit", str(work),
         "--lang", "zh"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, (
        f"audit non-aphasia cs paper failed: rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "0 findings (0 ERROR)" in result.stdout, (
        f"non-aphasia cs fixture should be fully clean; got:\n{result.stdout}"
    )


def test_audit_strict_passes(tmp_path):
    """--strict 也通过 — 0 ERROR 即满足 strict gate。"""
    work = tmp_path / "non_aphasia_cs"
    shutil.copytree(FIXTURE, work)

    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit", str(work),
         "--lang", "zh", "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, (
        f"audit --strict failed on clean fixture: rc={result.returncode}\n{result.stdout}"
    )


def test_audit_is_read_only(tmp_path):
    """L-033 硬约束：audit 必 read-only，paper.tex 字节级不可变动。"""
    work = tmp_path / "non_aphasia_cs"
    shutil.copytree(FIXTURE, work)
    paper_tex = work / "src" / "paper.tex"
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit", str(work),
         "--lang", "zh"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0

    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_before == sha_after, (
        "audit 修改了 paper.tex 字节 — 违反 L-033 唯一写入路径"
    )


def test_init_cs_field_succeeds(tmp_path):
    """paper-agent init --field cs --lang zh 必须成功（不 hardcode 任何 field）。"""
    work = tmp_path / "non_aphasia_cs"
    shutil.copytree(FIXTURE, work)

    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "init", str(work),
         "--lang", "zh", "--field", "cs"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, (
        f"init --field cs failed: rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert (work / ".latexmkrc").exists()
    assert (work / "compile.ps1").exists()
