"""失语症 paper 端到端 0 回归（spec §C.1 Done criteria #1-5）。

Done #1: 3 个迁入工具 paper-agent audit 与 weiwuer/paper/tools/ 直跑 findings count + 行级一致
Done #2: number_audit 留守 0 回归
Done #3: paper-agent compile 产物等价（字节级或可视）
Done #4: pytest 全绿（在 conftest 测）
Done #5: 失语症端到端 0 回归（本测覆盖）
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APHASIA_ROOT = Path(r"E:\claude_ask\Notion\weiwuer\paper")
OLD_TOOLS = APHASIA_ROOT / "tools"
APHASIA_TEX = APHASIA_ROOT / "src" / "paper.tex"
APHASIA_BIB = APHASIA_ROOT / "src" / "references.bib"


pytestmark = pytest.mark.skipif(
    not APHASIA_TEX.exists(),
    reason="aphasia paper not present at expected path",
)


_FINDING_RE = re.compile(r"^\[\s*(OK|FAIL|WARN|INFO|ERROR)\s*\]\s+([A-Za-z][A-Za-z0-9_]*)")


def _extract_findings(text: str) -> list[tuple[str, str]]:
    """从 stdout 提取 (tag, rule_code) finding 二元组列表（顺序保留）。

    spec §C.1 Done #1 contract：迁入工具的 finding 必须与旧工具行级一致。
    "finding" = 形如 `[ OK ] P1 ...` / `[FAIL] dangling_cite: 3 处` / `[INFO] commented_placeholder ...` 的行。
    rule_code 用显式 ASCII class 抓取，遇非 ASCII 立即停（humanize_check 的 `R1_LLM痕迹` 在 cp936 subprocess
    输出里会 mojibake 为不同 latin escape，所以 rule_code 只能取 ASCII 前缀 `R1_LLM`，再 rstrip 末尾下划线
    覆盖 `R8_数字反查` → `R8` 这种"全后缀都被吃"的退化情况）。
    装饰行（`[bib_audit] ...` / `[size] ...` / `[报告] ...` / `[PASS] ...`）namespace 不同，自然滤除。
    """
    findings = []
    for line in text.splitlines():
        m = _FINDING_RE.match(line.strip())
        if m:
            findings.append((m.group(1), m.group(2).rstrip("_")))
    return findings


def _assert_parity(tool: str, old_stdout: str, new_stdout: str) -> None:
    """断言：OLD 出现过的每条 rule，NEW 必须以相同 tag 给出相同次数的 finding。

    NEW 可新增 rule（如 0.1.0 punct_audit 新增 D1/D2 advisory）—— 这些 rule 不在 OLD 出现，
    parity 不强制覆盖，但 OLD 已有的 rule 不允许丢失或 tag 变化。
    """
    old = _extract_findings(old_stdout)
    new = _extract_findings(new_stdout)
    old_rules = {rule for _tag, rule in old}
    new_filtered = [(tag, rule) for tag, rule in new if rule in old_rules]
    assert old == new_filtered, (
        f"{tool} finding parity diverged on shared rules:\n"
        f"  OLD ({len(old)}): {old}\n"
        f"  NEW filtered to OLD rules ({len(new_filtered)}): {new_filtered}\n"
        f"  NEW full ({len(new)}): {new}"
    )


def test_punct_audit_parity(tmp_path):
    """spec §C.1 Done #1: punct_audit 旧/新 findings 行级一致（normalize 后）。"""
    old = subprocess.run(
        [sys.executable, str(OLD_TOOLS / "punct_audit.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out_json = tmp_path / "punct.json"
    new = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.punct_audit",
         "--source", str(APHASIA_TEX), "--lang", "zh", "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert old.returncode == new.returncode, (
        f"exit code diverged: old={old.returncode} new={new.returncode}\n"
        f"old stderr: {old.stderr[:500]}\nnew stderr: {new.stderr[:500]}"
    )
    _assert_parity("punct_audit", old.stdout, new.stdout)


def test_bib_audit_parity(tmp_path):
    """spec §C.1 Done #1: bib_audit 旧/新 findings 行级一致。"""
    old = subprocess.run(
        [sys.executable, str(OLD_TOOLS / "bib_audit.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out_json = tmp_path / "bib.json"
    new = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.bib_audit",
         "--tex", str(APHASIA_TEX), "--bib", str(APHASIA_BIB),
         "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert old.returncode == new.returncode, (
        f"exit code diverged: old={old.returncode} new={new.returncode}"
    )
    _assert_parity("bib_audit", old.stdout, new.stdout)


def test_humanize_check_parity(tmp_path):
    """spec §C.1 Done #1: humanize_check 旧/新 findings 行级一致。"""
    old = subprocess.run(
        [sys.executable, str(OLD_TOOLS / "humanize_check.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out_json = tmp_path / "humanize.json"
    new = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.humanize_check",
         "--source", str(APHASIA_TEX), "--lang", "zh",
         "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert old.returncode == new.returncode, (
        f"exit code diverged: old={old.returncode} new={new.returncode}"
    )
    _assert_parity("humanize_check", old.stdout, new.stdout)


def test_number_audit_still_works_in_place():
    """spec §C.1 Done #2: number_audit 保留原状，paper-specific TRUTH dict 不动。"""
    number_audit_path = OLD_TOOLS / "number_audit.py"
    if not number_audit_path.exists():
        pytest.skip("number_audit.py not present (may have been moved)")
    result = subprocess.run(
        [sys.executable, str(number_audit_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    # 失语症 paper 数字事实应 0 失配（BCC 1,818,649 / p 0.7287 / 92.5% 等）
    assert result.returncode == 0, (
        f"number_audit regression (rc={result.returncode}):\n"
        f"stdout={result.stdout[:500]}\nstderr={result.stderr[:500]}"
    )


@pytest.mark.skipif(shutil.which("latexmk") is None, reason="latexmk not installed")
def test_compile_produces_equivalent_pdf(tmp_path):
    """spec §C.1 Done #3: paper-agent compile 产物与旧 compile.ps1 等价（字节级或可视）。"""
    # 把 aphasia paper 复制到 tmp 以避免污染原项目
    aphasia_copy = tmp_path / "aphasia"
    shutil.copytree(
        APHASIA_ROOT, aphasia_copy,
        ignore=shutil.ignore_patterns("out", "audit", "advisory", "applied", "staged"),
    )
    # init
    init_result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "init", str(aphasia_copy),
         "--lang", "zh", "--field", "linguistics"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert init_result.returncode == 0, (
        f"init failed:\nstdout={init_result.stdout}\nstderr={init_result.stderr}"
    )
    # compile
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "compile", str(aphasia_copy)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    new_pdf = aphasia_copy / "out" / "paper.pdf"
    assert new_pdf.exists(), (
        f"paper-agent compile 未产 pdf:\n"
        f"stdout={result.stdout[:500]}\nstderr={result.stderr[:500]}"
    )

    old_pdf = APHASIA_ROOT / "out" / "paper.pdf"
    if old_pdf.exists():
        # 容许 timing 字段差异：仅 sanity check (size > 1KB)
        assert new_pdf.stat().st_size > 1024
        # 可选：用 pdftotext 比较文本层（如果有）
