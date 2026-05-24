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


# ============================================================
# Platform abstraction: flock + TTY
# ============================================================

def _is_real_tty() -> bool:
    """信任锚校验：stdin AND stdout 都是真 TTY（pipe/heredoc/agent IPC 一律否）。"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _acquire_exclusive_lock(file_obj) -> None:
    """排他写锁（持锁直到 file_obj.close()）。

    - Windows: msvcrt.locking(LK_NBLCK) — non-blocking, 失败抛 OSError
    - Unix:    fcntl.flock(LOCK_EX | LOCK_NB) — 同上
    """
    if sys.platform == "win32":
        import msvcrt
        try:
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 0x7FFFFFFF)
        except OSError as e:
            raise BlockingIOError(f"file already locked: {e}") from e
    else:
        import fcntl
        try:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise
        except OSError as e:
            raise BlockingIOError(f"file already locked: {e}") from e


def _read_tty_answer(prompt: str) -> str:
    """从真实终端 (CON / /dev/tty) 读一行，不接受 sys.stdin。"""
    tty_path = "CON" if sys.platform == "win32" else "/dev/tty"
    with open(tty_path, "r", encoding="utf-8") as tty_in:
        print(prompt, end="", flush=True)
        return tty_in.readline().strip().lower()


def _print_colored_diff_full(diff_text: str) -> None:
    """打印完整 diff（无折叠）。强制全文展示是 T5 indirect injection 缓解。"""
    # 0.1.0 placeholder — colorama integration deferred (name reserved for ANSI rendering)
    print(diff_text)


# ---------------------------------------------------------------------------
# Layer 3 exceptions
# ---------------------------------------------------------------------------

class EditGateError(Exception):
    """Base exception for all edit_gate() failures."""


class NonInteractiveSession(EditGateError):
    """Raised when stdin/stdout is not a real TTY."""


class FileMutatedSinceAdvisory(EditGateError):
    """Raised when paper.tex sha256 changed since advisory was created."""


class PatchContextMismatch(EditGateError):
    """Raised when diff context lines do not match current file content (fuzz=0)."""


class UserDenied(EditGateError):
    """Raised when user answers anything other than 'y' / 'yes' at confirmation prompt."""


# ---------------------------------------------------------------------------
# Layer 3 result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EditResult:
    diff_id: str
    applied_dir: str
    backup_path: str
    post_apply_sha256: str


# ---------------------------------------------------------------------------
# Layer 3 internal: strict unified-diff applier (no external `patch` binary)
# ---------------------------------------------------------------------------

def _parse_hunks(diff_text: str) -> list[dict]:
    """Parse unified diff hunks.

    Returns list of dicts, each with:
        old_start: int   (1-based line number in original)
        old_count: int
        new_start: int
        new_count: int
        lines: list[str]  (raw diff lines including +/-/space, no newlines stripped)
    """
    hunks = []
    current_hunk: dict | None = None
    for raw_line in diff_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if line.startswith("@@"):
            # @@ -old_start[,old_count] +new_start[,new_count] @@
            import re
            m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                current_hunk = {
                    "old_start": int(m.group(1)),
                    "old_count": int(m.group(2)) if m.group(2) is not None else 1,
                    "new_start": int(m.group(3)),
                    "new_count": int(m.group(4)) if m.group(4) is not None else 1,
                    "lines": [],
                }
                hunks.append(current_hunk)
        elif current_hunk is not None:
            if raw_line.startswith(("+", "-", " ")):
                current_hunk["lines"].append(raw_line)
    return hunks


def _apply_patch_strict(original: str, diff_text: str) -> str:
    """Apply a unified diff to original text with fuzz=0 (strict context match).

    Takes original file content as a string, applies all hunks, returns new content.
    Does NOT read from or write to disk — caller is responsible for I/O.

    Raises PatchContextMismatch if any context or removed line does not
    exactly match the original content (no fuzz, no whitespace tolerance).
    """
    lines = original.splitlines(keepends=True)

    hunks = _parse_hunks(diff_text)
    if not hunks:
        raise PatchContextMismatch("diff_text contains no parseable hunks")

    # Apply hunks in reverse order to avoid line number shifts
    for hunk in reversed(hunks):
        old_start = hunk["old_start"]  # 1-based
        hunk_lines = hunk["lines"]

        # Collect context + removed lines to verify against file
        expected_old: list[str] = []
        new_chunk: list[str] = []

        for raw in hunk_lines:
            if not raw:
                continue
            prefix = raw[0]
            content = raw[1:]  # strip leading +/-/space marker
            if prefix == " ":
                expected_old.append(content)
                new_chunk.append(content)
            elif prefix == "-":
                expected_old.append(content)
                # Don't include in new_chunk (removal)
            elif prefix == "+":
                new_chunk.append(content)

        # Verify context/removed lines match file content (fuzz=0)
        # old_start is 1-based; slice is 0-based
        start_idx = old_start - 1
        end_idx = start_idx + len(expected_old)

        if end_idx > len(lines):
            raise PatchContextMismatch(
                f"Hunk @@ -{old_start} extends beyond file length {len(lines)}"
            )

        actual_slice = [l.rstrip("\r\n") for l in lines[start_idx:end_idx]]
        expected_stripped = [e.rstrip("\r\n") for e in expected_old]

        if actual_slice != expected_stripped:
            raise PatchContextMismatch(
                f"Context mismatch at line {old_start}: "
                f"expected {expected_stripped!r}, got {actual_slice!r}"
            )

        # Determine line ending from original lines in the slice
        ending = "\n"
        if lines and lines[0].endswith("\r\n"):
            ending = "\r\n"

        # Build new_chunk with proper line endings
        new_chunk_with_endings = []
        for c in new_chunk:
            stripped = c.rstrip("\r\n")
            new_chunk_with_endings.append(stripped + ending)

        # Replace slice in lines list
        lines[start_idx:end_idx] = new_chunk_with_endings

    return "".join(lines)


# ---------------------------------------------------------------------------
# Layer 3: edit_gate() — the ONLY path that writes paper.tex
# ---------------------------------------------------------------------------

def edit_gate(
    paper_root: Any,
    diff_id: str,
    paper_name: str = "paper",
) -> EditResult:
    """Layer 3: apply advisory patch to paper.tex after full security gating.

    Gate order (non-negotiable, per L-033):
      1. Real TTY check → NonInteractiveSession if False
      2. Read advisory meta.json + diff.patch → FileNotFoundError if missing
      3. Acquire exclusive lock on paper.tex
      4. Re-verify sha256 under lock → FileMutatedSinceAdvisory if mismatch
      5. Print full diff + prompt user via real TTY
      6. Apply patch strictly (fuzz=0) → PatchContextMismatch on mismatch
      7. Archive diff to applied/<diff_id>/
      8. Write backup paper.tex.bak.<timestamp>
      9. Lock released on with-block exit

    Args:
        paper_root: Path-like root of the paper project.
        diff_id:    Advisory diff ID (16-char hex).
        paper_name: LaTeX paper base name (default "paper").

    Returns:
        EditResult with diff_id, applied_dir, backup_path, post_apply_sha256.

    Raises:
        NonInteractiveSession:   stdin/stdout not a real TTY.
        FileNotFoundError:       advisory dir / meta.json / diff.patch missing.
        FileMutatedSinceAdvisory: paper.tex sha256 changed since advisory.
        PatchContextMismatch:    diff context doesn't match file content.
        UserDenied:              user typed anything other than 'y' / 'yes'.
    """
    # ---- Gate 1: real TTY -----------------------------------------------
    if not _is_real_tty():
        raise NonInteractiveSession(
            "edit_gate() requires a real TTY (stdin and stdout must be a terminal). "
            "Refusing to write paper.tex in non-interactive session."
        )

    # ---- Gate 2: read advisory ------------------------------------------
    paper_root = Path(paper_root).resolve()
    advisory_dir = paper_root / "advisory" / diff_id
    meta_path = advisory_dir / "meta.json"
    patch_path = advisory_dir / "diff.patch"

    if not meta_path.exists():
        raise FileNotFoundError(f"Advisory meta.json not found: {meta_path}")
    if not patch_path.exists():
        raise FileNotFoundError(f"Advisory diff.patch not found: {patch_path}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    expected_sha = meta["expected_file_sha256"]
    diff_text = patch_path.read_text(encoding="utf-8")

    paper_tex = paper_root / "src" / f"{paper_name}.tex"

    # ---- Gate 3+4: acquire lock, re-verify sha256 -----------------------
    with open(paper_tex, "r+b") as f:
        _acquire_exclusive_lock(f)

        # Re-read sha256 INSIDE the lock (f is already at position 0 after seek in lock)
        raw_bytes = f.read()
        current_sha = hashlib.sha256(raw_bytes).hexdigest()
        if current_sha != expected_sha:
            raise FileMutatedSinceAdvisory(
                f"paper.tex has changed since advisory was created.\n"
                f"  Advisory expected: {expected_sha}\n"
                f"  Current sha256:    {current_sha}\n"
                f"Re-run advisory() to generate a fresh patch."
            )

        # Decode original content from the already-read bytes
        original_content = raw_bytes.decode("utf-8")

        # ---- Gate 5: print diff + TTY confirm ---------------------------
        _print_colored_diff_full(diff_text)
        answer = _read_tty_answer(
            f"\nApply patch {diff_id} to {paper_tex.name}? [y/N] "
        )
        if answer not in ("y", "yes"):
            raise UserDenied(
                f"User declined to apply patch {diff_id!r} (answered: {answer!r})."
            )

        # ---- Gate 6: apply patch (compute new content, no disk I/O yet) -
        new_content = _apply_patch_strict(original_content, diff_text)
        new_bytes = new_content.encode("utf-8")
        post_sha = hashlib.sha256(new_bytes).hexdigest()

        # Write new content back via the locked file handle (truncate + overwrite)
        f.seek(0)
        f.write(new_bytes)
        f.truncate()
        f.flush()

        # ---- Gate 7: archive to applied/ --------------------------------
        import shutil
        applied_root = paper_root / "applied"
        applied_dest = applied_root / diff_id
        applied_dest.mkdir(parents=True, exist_ok=True)
        for src_file in advisory_dir.iterdir():
            shutil.copy2(src_file, applied_dest / src_file.name)
        # Also write post_apply_sha256 to applied/ meta
        post_meta = dict(meta)
        post_meta["post_apply_sha256"] = post_sha
        post_meta["applied_at"] = datetime.now(timezone.utc).isoformat()
        (applied_dest / "meta.json").write_text(
            json.dumps(post_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ---- Gate 8: backup of the ORIGINAL content before patch ---------
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = paper_tex.with_suffix(f".tex.bak.{ts}")
        backup_path.write_bytes(raw_bytes)

        # ---- Lock released on `with` exit (Gate 9) ----------------------

    return EditResult(
        diff_id=diff_id,
        applied_dir=str(applied_dest),
        backup_path=str(backup_path),
        post_apply_sha256=post_sha,
    )
