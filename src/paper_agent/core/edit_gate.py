"""L-033 升级版三层网关（spec §D.1）：audit → advisory → edit_gate。

Layer 1 (audit):    read-only, 跑规则返 Finding list
Layer 2 (advisory): read-only + 写 advisory/<diff_id>/，提议 patch，不动 paper.tex
Layer 3 (edit_gate): write，必须真实 TTY + flock + sha256 重算 + patch --strict
                     （Layer 3 在 T10 实现）
"""
from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Finding:
    rule: str
    severity: str          # ERROR / WARN / INFO
    file: str
    line: int
    col: int | None = None
    message: str = ""
    suggested_fix: str | None = None


@dataclass
class Patch:
    diff_id: str
    advisory_dir: str
    expected_file_sha256: str
    diff: str
    rule: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RULE_MODULE_MAP = {
    "punct": "paper_agent.audit.rule.punct_audit",
    "bib": "paper_agent.audit.rule.bib_audit",
    "humanize": "paper_agent.audit.rule.humanize_check",
}


def _normalize_finding(r: dict, module: str) -> dict:
    """Normalize a raw finding dict from any rule module into a common shape.

    Rule modules emit inconsistent discriminator field names:
      punct_audit   → "check"  (e.g. "P1", "P5")
      bib_audit     → "type"   (e.g. "dangling_cite", "todo_placeholder")
      humanize_check→ "rule"   (e.g. "R1_LLM痕迹", "R8_数字反查")

    After normalization all dicts have a "rule" key and all fields expected
    by the Finding dataclass.
    """
    r2 = dict(r)
    if "rule" not in r2:
        r2["rule"] = r2.pop("check", None) or r2.pop("type", None) or ""
    r2.setdefault("severity", "WARN")
    r2.setdefault("file", "")
    r2.setdefault("line", 0)
    r2.setdefault("message", "")
    r2.setdefault("col", None)
    r2.setdefault("suggested_fix", None)
    return r2


def _finding_from_dict(r: dict, module: str) -> Finding:
    """Build a Finding from a normalized dict, ignoring extra keys."""
    r2 = _normalize_finding(r, module)
    return Finding(
        rule=r2["rule"],
        severity=r2["severity"],
        file=r2["file"],
        line=r2["line"],
        col=r2.get("col"),
        message=r2["message"],
        suggested_fix=r2.get("suggested_fix"),
    )


def _run_rule_module(
    module_name: str,
    extra_args: list[str],
    paper_root: Path,
) -> list[Finding]:
    """Run a rule module as a subprocess, return normalized Finding list.

    extra_args must include --out <path>; the output path is extracted from
    extra_args so the caller controls where output lands (e.g. audit/<run_id>/).
    paper.tex is never touched.
    """
    # Extract out_path from extra_args (caller always passes --out)
    if "--out" in extra_args:
        out_path = Path(extra_args[extra_args.index("--out") + 1])
    else:
        # Fallback: write to audit/ flat (should not normally happen)
        audit_dir = paper_root / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        safe_name = module_name.replace(".", "_")
        out_path = audit_dir / f"{safe_name}_out.json"
        extra_args = extra_args + ["--out", str(out_path)]

    cmd = [
        sys.executable,
        "-m",
        module_name,
    ] + extra_args

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # Exit code 1 = findings present (normal for audit); 2 = missing file (error)
    if result.returncode == 2:
        raise RuntimeError(
            f"{module_name} exited with code 2 (missing file?)\n"
            f"stderr: {result.stderr}"
        )

    if not out_path.exists():
        # Module didn't write output (may have exited 0 with no findings)
        return []

    data = json.loads(out_path.read_text(encoding="utf-8"))
    # Unwrap wrapper object: all three modules wrap findings in {"findings": [...]}
    raw = data["findings"] if isinstance(data, dict) and "findings" in data else data
    if not isinstance(raw, list):
        raw = []

    findings = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        findings.append(_finding_from_dict(r, module_name))
    return findings


# ---------------------------------------------------------------------------
# Layer 1: audit (read-only)
# ---------------------------------------------------------------------------

def audit(
    paper_root: Any,
    rules: list[str] | None = None,
    lang: str = "zh",
    paper_name: str = "paper",
) -> list[Finding]:
    """Layer 1: run rule modules read-only; return list of Finding.

    paper.tex sha256 is guaranteed unchanged — the rule modules themselves
    only read; audit output JSONs are written to paper_root/audit/ (sibling dir).

    Args:
        paper_root: Path-like root of the paper project.
        rules:      Subset of ["punct", "bib", "humanize"] to run.
                    Defaults to all three.
        lang:       Language tag passed to rule modules (default "zh").

    Returns:
        Flat list of Finding across all requested rule modules.
    """
    paper_root = Path(paper_root).resolve()
    if rules is None:
        rules = ["punct", "bib", "humanize"]

    src_dir = paper_root / "src"
    paper_tex = src_dir / f"{paper_name}.tex"
    bib_file = src_dir / "references.bib"

    audit_dir = paper_root / "audit"
    audit_dir.mkdir(exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = audit_dir / run_id
    run_dir.mkdir(exist_ok=True)

    all_findings: list[Finding] = []

    for rule in rules:
        module = _RULE_MODULE_MAP.get(rule)
        if module is None:
            raise ValueError(f"Unknown rule set: {rule!r}. Known: {list(_RULE_MODULE_MAP)}")

        out_path = run_dir / f"{rule}.json"

        if rule == "punct":
            if not paper_tex.exists():
                continue
            extra = ["--source", str(paper_tex), "--lang", lang, "--out", str(out_path)]
        elif rule == "bib":
            if not paper_tex.exists() or not bib_file.exists():
                continue
            extra = ["--tex", str(paper_tex), "--bib", str(bib_file), "--out", str(out_path)]
        elif rule == "humanize":
            if not paper_tex.exists():
                continue
            extra = ["--source", str(paper_tex), "--lang", lang, "--out", str(out_path)]
        else:
            extra = []

        findings = _run_rule_module(module, extra, paper_root)
        all_findings.extend(findings)

    return all_findings


# ---------------------------------------------------------------------------
# Layer 2: advisory (read-only + writes advisory/<diff_id>/)
# ---------------------------------------------------------------------------

def _build_diff(before_lines: list[str], after_lines: list[str], filename: str = "paper.tex") -> str:
    """Build a unified diff string (n=3 context lines)."""
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3,
        )
    )


def _diff_id(sha: str, rule: str, line: int, col: Any) -> str:
    """Deterministic diff_id: sha256(sha|rule|line|col)[:16].

    col=None is interpolated as the literal string "None" via f-string default;
    this is the spec formula (plan line 1396) and must stay stable across commits.
    """
    h = hashlib.sha256(f"{sha}|{rule}|{line}|{col}".encode()).hexdigest()
    return h[:16]


def advisory(
    paper_root: Any,
    rules: list[str] | None = None,
    lang: str = "zh",
    paper_name: str = "paper",
) -> list[dict]:
    """Layer 2: run audit(), then write advisory/<diff_id>/ for findings with suggested_fix.

    paper.tex is NEVER modified.  Only advisory/<diff_id>/ directories are created.

    Each advisory dir contains:
        meta.json     – metadata including expected_file_sha256, diff_id, created_at
        before.txt    – the original line(s)
        after.txt     – the suggested fixed line(s)
        diff.patch    – unified diff of before vs after

    Args:
        paper_root: Path-like root of the paper project.
        rules:      Subset of ["punct", "bib", "humanize"] to run.
        lang:       Language tag.

    Returns:
        List of patch dicts (one per advisory dir created), each with keys:
            diff_id, advisory_dir, expected_file_sha256, diff, rule
    """
    paper_root = Path(paper_root).resolve()
    src_dir = paper_root / "src"
    paper_tex = src_dir / f"{paper_name}.tex"

    # Compute sha256 of paper.tex before anything
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    findings = audit(paper_root, rules=rules, lang=lang, paper_name=paper_name)

    # Filter to findings that have a suggested_fix
    actionable = [f for f in findings if f.suggested_fix is not None]

    patches: list[dict] = []
    if not actionable:
        return patches

    tex_lines = paper_tex.read_text(encoding="utf-8").splitlines(keepends=True)
    advisory_root = paper_root / "advisory"
    advisory_root.mkdir(parents=True, exist_ok=True)

    for finding in actionable:
        did = _diff_id(sha_before, finding.rule, finding.line, finding.col)
        advisory_dir = advisory_root / did
        advisory_dir.mkdir(parents=True, exist_ok=True)

        # Build before/after from the identified line (1-indexed → 0-indexed)
        line_idx = finding.line - 1 if finding.line > 0 else 0
        if 0 <= line_idx < len(tex_lines):
            before_line = tex_lines[line_idx]
            after_line = finding.suggested_fix
            # Preserve line ending from before
            if before_line.endswith("\r\n"):
                after_line = after_line.rstrip("\r\n") + "\r\n"
            elif before_line.endswith("\n"):
                after_line = after_line.rstrip("\r\n") + "\n"
            before_lines = [before_line]
            after_lines = [after_line]
        else:
            before_lines = []
            after_lines = [finding.suggested_fix]

        diff_text = _build_diff(before_lines, after_lines, f"{paper_name}.tex")

        (advisory_dir / "before.txt").write_text(
            "".join(before_lines), encoding="utf-8"
        )
        (advisory_dir / "after.txt").write_text(
            "".join(after_lines), encoding="utf-8"
        )
        (advisory_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

        meta = {
            "diff_id": did,
            "rule": finding.rule,
            "severity": finding.severity,
            "file": str(paper_tex),
            "line": finding.line,
            "col": finding.col,
            "message": finding.message,
            "expected_file_sha256": sha_before,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (advisory_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        patches.append(
            {
                "diff_id": did,
                "advisory_dir": str(advisory_dir),
                "expected_file_sha256": sha_before,
                "diff": diff_text,
                "rule": finding.rule,
            }
        )

    # Verify paper.tex was NOT modified
    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_after == sha_before, (
        "INTERNAL ERROR: advisory() modified paper.tex — L-033 violation"
    )

    return patches
