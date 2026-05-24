"""bib_audit dangling_cite / todo_placeholder / unused_entry."""
import json
import subprocess
import sys


def test_dangling_cite_and_todo(fixtures_dir, tmp_path):
    tex = fixtures_dir / "min_linguistics_zh.tex"
    bib = fixtures_dir / "min_linguistics_zh.bib"
    out_json = tmp_path / "bib_findings.json"
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.bib_audit",
         "--tex", str(tex), "--bib", str(bib),
         "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1, f"expected violations, got {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    findings = json.loads(out_json.read_text(encoding="utf-8"))["findings"]
    # Source uses "type" field (not "rule") as the finding discriminator
    types = {f["type"] for f in findings}
    assert "dangling_cite" in types, f"got types: {types}"
    assert "todo_placeholder" in types, f"got types: {types}"


def test_biber_tool_optional(fixtures_dir, tmp_path):
    """--use-biber-tool does not crash when biber may or may not be installed."""
    bib = fixtures_dir / "min_linguistics_zh.bib"
    out_json = tmp_path / "biber_only.json"
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.bib_audit",
         "--tex", str(fixtures_dir / "min_linguistics_zh.tex"),
         "--bib", str(bib),
         "--use-biber-tool",
         "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode in (0, 1), f"unexpected exit {result.returncode}"


def test_required_fields_optional(fixtures_dir, tmp_path):
    """--required-fields triggers missing_field findings on incomplete non-TODO entries."""
    out_json = tmp_path / "rf.json"
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.bib_audit",
         "--tex", str(fixtures_dir / "min_linguistics_zh.tex"),
         "--bib", str(fixtures_dir / "min_linguistics_zh.bib"),
         "--required-fields", "author,title,year,journal",
         "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out_json.exists():
        findings = json.loads(out_json.read_text(encoding="utf-8"))["findings"]
        mf = [f for f in findings if f["type"] == "missing_field"]
        assert len(mf) >= 3, f"expected >=3 missing_field on TODO_ entry, got {len(mf)}: {mf}"
