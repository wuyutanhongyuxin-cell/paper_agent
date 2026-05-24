"""humanize_check R1-R7 char-level + R8 number cross-reference.

F9 field-name mapping: source has stdout-only output; migrated module emits
findings dicts with field name "rule" (e.g. "R1_LLM痕迹", "R8_数字反查").
The "rule" field is what we assert against.

Subprocess tests require main-session rerun on win32 (WinError 5 in sandbox).
DO NOT skipif win32 — main session IS win32 (F6).
"""
import json
import subprocess
import sys


def test_r1_to_r7_detected(fixtures_dir, tmp_path):
    """R1-R7 all trigger on min_linguistics_zh.tex which has deliberate violations."""
    tex = fixtures_dir / "min_linguistics_zh.tex"
    out_json = tmp_path / "humanize.json"
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.humanize_check",
         "--source", str(tex), "--lang", "zh",
         "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1, (
        f"expected violations (rc=1), got {result.returncode}\n"
        f"stdout={result.stdout[:500]}\nstderr={result.stderr[:500]}"
    )
    findings = json.loads(out_json.read_text(encoding="utf-8"))["findings"]
    # field name is "rule" per F9 recon (migrated module uses f["rule"])
    rules = {f["rule"] for f in findings}
    for r in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
        assert any(r in x for x in rules), f"{r} not triggered, got: {rules}"


def test_r8_number_lookup_match(fixtures_dir, tmp_path):
    """R8: numbers in data-source match → no finding; 999999 not in source → finding."""
    tex = fixtures_dir / "min_linguistics_zh.tex"
    data = fixtures_dir / "min_humanize_data.json"
    out_json = tmp_path / "humanize_r8.json"
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.humanize_check",
         "--source", str(tex), "--lang", "zh",
         "--data-source", str(data),
         "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8",
    )
    # R1-R7 violations exist in the fixture → exit code 1
    # R8 WARN does not affect exit code per source semantics
    assert result.returncode in (0, 1), (
        f"unexpected exit code {result.returncode}\n"
        f"stdout={result.stdout[:500]}\nstderr={result.stderr[:500]}"
    )
    assert out_json.exists(), "humanize_check should write --out JSON"
    findings = json.loads(out_json.read_text(encoding="utf-8"))["findings"]
    # R8 findings use rule="R8_数字反查" and token field for the unmatched number
    r8 = [f for f in findings if "R8" in f["rule"]]
    tokens_unmatched = {f.get("token") or f.get("message", "") for f in r8}
    assert any("999999" in t for t in tokens_unmatched), (
        f"expected 999999 in R8 unmatched tokens, got: {tokens_unmatched}"
    )
    assert not any("1,818,649" in t for t in tokens_unmatched), (
        f"1,818,649 should match data-source thousands list, got R8 unmatched: {tokens_unmatched}"
    )
    assert not any("0.7287" in t for t in tokens_unmatched), (
        f"0.7287 should match data-source p_values, got R8 unmatched: {tokens_unmatched}"
    )


def test_lang_en_placeholder_does_not_explode(tmp_path):
    """lang=en has RULES={}; R1 empty regex must not match every position (no-match fallback)."""
    clean_tex = tmp_path / "clean.tex"
    clean_tex.write_text(
        r"""\documentclass{article}
\begin{document}
Hello world.
\end{document}
""",
        encoding="utf-8",
    )
    out_json = tmp_path / "humanize_en.json"
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.audit.rule.humanize_check",
         "--source", str(clean_tex), "--lang", "en", "--out", str(out_json)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"clean en file should pass with R1-R3 empty rules, got rc={result.returncode}\n"
        f"stdout={result.stdout[:500]}\nstderr={result.stderr[:500]}"
    )
    findings = json.loads(out_json.read_text(encoding="utf-8"))["findings"]
    assert findings == [], f"R1/R2/R3 empty regex should not produce findings on clean file, got: {findings[:5]}"
