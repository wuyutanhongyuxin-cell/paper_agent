"""Tests for paper_agent.audit.rule.punct_audit.

Subprocess-based tests are marked; they require the full Python environment
(WinError 5 sandbox restriction means they cannot self-verify — deferred to
main session).  Import-level tests can run without subprocess.
"""
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Smoke import (no subprocess needed)
# ---------------------------------------------------------------------------

def test_module_imports():
    """The migrated module must be importable without side effects."""
    import paper_agent.audit.rule.punct_audit as pa  # noqa: F401
    assert callable(pa.main)
    assert callable(pa.check_math_envir)
    assert callable(pa.check_dangling_refs)


# ---------------------------------------------------------------------------
# Unit-level checks (no subprocess, no file I/O)
# ---------------------------------------------------------------------------

def test_check_math_envir_unclosed_dollar():
    from paper_agent.audit.rule.punct_audit import check_math_envir
    body = r"$x = 1"  # odd number of $
    findings = check_math_envir(body)
    assert any(f["type"] == "unclosed_math_dollar" for f in findings)


def test_check_math_envir_balanced():
    from paper_agent.audit.rule.punct_audit import check_math_envir
    body = r"$x = 1$ and $y = 2$"
    findings = check_math_envir(body)
    assert findings == []


def test_check_dangling_refs_detects():
    from paper_agent.audit.rule.punct_audit import check_dangling_refs
    body = r"\ref{undefined_label}"
    findings = check_dangling_refs(body)
    assert any(f["key"] == "undefined_label" for f in findings)


def test_check_dangling_refs_ok():
    from paper_agent.audit.rule.punct_audit import check_dangling_refs
    body = r"\label{sec:intro} see \ref{sec:intro}"
    findings = check_dangling_refs(body)
    assert findings == []


# ---------------------------------------------------------------------------
# Subprocess-based integration tests
# DEFERRED to main session (sandbox WinError 5 blocks subprocess.run).
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    sys.platform == "win32",
    reason="subprocess.run([sys.executable, ...]) blocked by sandbox WinError 5 — run in main session"
)
def test_detects_p1_through_p9(fixtures_dir, tmp_path):
    """Fixture has P1 (ASCII \"), P5 (half-width comma), P8 (unclosed $), P9 (dangling ref).
    Exit code must be 1; --out JSON must contain all four checks.
    """
    import subprocess
    tex = fixtures_dir / "min_linguistics_zh.tex"
    out_json = tmp_path / "findings.json"

    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.punct_audit",
         "--source", str(tex), "--lang", "zh", "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    assert out_json.exists(), "--out file not created"

    data = json.loads(out_json.read_text(encoding="utf-8"))
    checks_hit = {f["check"] for f in data["findings"]}
    # fixture has ASCII ", half-width comma, unclosed $, dangling ref
    assert "P1" in checks_hit, f"P1 not in findings: {checks_hit}"
    assert "P5" in checks_hit, f"P5 not in findings: {checks_hit}"
    assert "P8" in checks_hit, f"P8 not in findings: {checks_hit}"
    assert "P9" in checks_hit, f"P9 not in findings: {checks_hit}"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="subprocess blocked — deferred to main session"
)
def test_pdf_mode_optional(fixtures_dir, tmp_path):
    """--pdf flag must not crash; exit code reflects findings in the file."""
    import subprocess
    tex = fixtures_dir / "min_linguistics_zh.tex"
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.punct_audit",
         "--source", str(tex), "--pdf", "--lang", "zh"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode in (0, 1), (
        f"Expected 0 or 1, got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="subprocess blocked — deferred to main session"
)
def test_lang_en_placeholder_does_not_crash(tmp_path):
    """lang=en has no punct_patterns → P1-P7 skipped; P8/P9 on empty file → exit 0."""
    import subprocess
    clean_tex = tmp_path / "clean.tex"
    clean_tex.write_text(
        r"""\documentclass{article}
\begin{document}
Hello world.
\end{document}
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.punct_audit",
         "--source", str(clean_tex), "--lang", "en"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"Expected 0 for clean file with lang=en, got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
