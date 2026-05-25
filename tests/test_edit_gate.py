"""Red-team tests for edit_gate() Layer 3 — T1 through T6.

Each test exercises exactly one security gate in the L-033 spec.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


# ---------------------------------------------------------------------------
# Shared fixture: minimal advisory + paper root
# ---------------------------------------------------------------------------

@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def paper_root(tmp_path, fixtures_dir):
    """Set up a minimal paper root with src/paper.tex and a valid advisory."""
    root = tmp_path / "paper"
    (root / "src").mkdir(parents=True)
    shutil.copy(fixtures_dir / "min_linguistics_zh.tex", root / "src" / "paper.tex")
    return root


def _make_advisory(paper_root: Path) -> dict:
    """Create a minimal valid advisory dir and return meta dict.

    Returns dict with keys: diff_id, expected_sha, diff_text, advisory_dir.
    """
    paper_tex = paper_root / "src" / "paper.tex"
    content = paper_tex.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    sha = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    # Build a trivial 1-line patch: replace line 3 content with same + trailing space stripped
    # Use line 3 (section header) for a safe, predictable change
    line_idx = 2  # 0-based, line 3
    old_line = lines[line_idx]
    # Make a real change: append a comment so patch is non-trivial
    new_line = old_line.rstrip("\r\n") + "% patched\n"

    # Build unified diff manually
    old_lines_for_diff = [old_line]
    new_lines_for_diff = [new_line]

    import difflib
    diff_text = "".join(
        difflib.unified_diff(
            old_lines_for_diff,
            new_lines_for_diff,
            fromfile="a/paper.tex",
            tofile="b/paper.tex",
            n=0,  # 0 context lines for simplicity
        )
    )
    # Use a fixed diff_id for reproducibility in tests
    diff_id = hashlib.sha256(f"{sha}|test|3|None".encode()).hexdigest()[:16]

    advisory_dir = paper_root / "advisory" / diff_id
    advisory_dir.mkdir(parents=True, exist_ok=True)

    (advisory_dir / "before.txt").write_text(old_line, encoding="utf-8")
    (advisory_dir / "after.txt").write_text(new_line, encoding="utf-8")
    (advisory_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    meta = {
        "diff_id": diff_id,
        "rule": "test_rule",
        "severity": "WARN",
        "file": str(paper_tex),
        "line": 3,
        "col": None,
        "message": "test patch",
        "expected_file_sha256": sha,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (advisory_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "diff_id": diff_id,
        "expected_sha": sha,
        "diff_text": diff_text,
        "advisory_dir": advisory_dir,
    }


# ---------------------------------------------------------------------------
# T1: NonInteractiveSession — TTY guard blocks non-TTY callers
# ---------------------------------------------------------------------------

def test_t1_non_interactive_session(paper_root):
    """Gate 1: edit_gate() raises NonInteractiveSession when not a real TTY.

    In pytest, _is_real_tty() returns False (stdin/stdout are pipes).
    edit_gate() must raise before touching anything.
    """
    from paper_agent.core.edit_gate import edit_gate, NonInteractiveSession

    adv = _make_advisory(paper_root)
    paper_tex = paper_root / "src" / "paper.tex"
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    with pytest.raises(NonInteractiveSession):
        edit_gate(paper_root, adv["diff_id"])

    # paper.tex must be untouched
    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_before == sha_after


# ---------------------------------------------------------------------------
# T2: FileMutatedSinceAdvisory — sha256 re-check under lock
# ---------------------------------------------------------------------------

def test_t2_file_mutated_since_advisory(paper_root):
    """Gate 4: edit_gate() raises FileMutatedSinceAdvisory if file changed after advisory.

    Mocks _is_real_tty() to True and mutates paper.tex after advisory is created.
    """
    from paper_agent.core.edit_gate import edit_gate, FileMutatedSinceAdvisory

    adv = _make_advisory(paper_root)
    paper_tex = paper_root / "src" / "paper.tex"

    # Mutate paper.tex after advisory was created
    original = paper_tex.read_text(encoding="utf-8")
    paper_tex.write_text(original + "\n% mutated after advisory\n", encoding="utf-8")

    with mock.patch("paper_agent.core.edit_gate._is_real_tty", return_value=True):
        with pytest.raises(FileMutatedSinceAdvisory):
            edit_gate(paper_root, adv["diff_id"])


# ---------------------------------------------------------------------------
# T3: FileNotFoundError — missing advisory
# ---------------------------------------------------------------------------

def test_t3_missing_advisory(paper_root):
    """Gate 2: edit_gate() raises FileNotFoundError for non-existent diff_id.

    Uses a subprocess to test that the error is correctly propagated even
    when _is_real_tty() is True (mocked via env var injection isn't feasible
    in subprocess; use a helper script instead).
    """
    from paper_agent.core.edit_gate import edit_gate, NonInteractiveSession

    # This test runs in-process with _is_real_tty mocked.
    # Gate 1 (TTY) is mocked to True so we reach Gate 2 (file read).
    fake_diff_id = "deadbeef12345678"

    with mock.patch("paper_agent.core.edit_gate._is_real_tty", return_value=True):
        with pytest.raises(FileNotFoundError):
            edit_gate(paper_root, fake_diff_id)


# ---------------------------------------------------------------------------
# T4: PatchContextMismatch — corrupt diff context
# ---------------------------------------------------------------------------

def test_t4_patch_context_mismatch(paper_root):
    """Gate 6: edit_gate() raises PatchContextMismatch when diff context is wrong.

    Creates an advisory whose diff.patch references a line that doesn't exist
    in current paper.tex (context was fabricated/corrupt).
    """
    from paper_agent.core.edit_gate import edit_gate, PatchContextMismatch

    paper_tex = paper_root / "src" / "paper.tex"
    sha = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    # Build a diff with wrong context (line content that is NOT in paper.tex)
    corrupt_diff = (
        "--- a/paper.tex\n"
        "+++ b/paper.tex\n"
        "@@ -3,1 +3,1 @@\n"
        "-THIS LINE DOES NOT EXIST IN paper.tex XYZZY_CORRUPT\n"
        "+replacement line\n"
    )

    diff_id = "corrupt000000001"
    advisory_dir = paper_root / "advisory" / diff_id
    advisory_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "diff_id": diff_id,
        "rule": "test",
        "severity": "WARN",
        "file": str(paper_tex),
        "line": 3,
        "col": None,
        "message": "corrupt test",
        "expected_file_sha256": sha,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (advisory_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (advisory_dir / "diff.patch").write_text(corrupt_diff, encoding="utf-8")

    with mock.patch("paper_agent.core.edit_gate._is_real_tty", return_value=True):
        with mock.patch("paper_agent.core.edit_gate._read_tty_answer", return_value="y"):
            with pytest.raises(PatchContextMismatch):
                edit_gate(paper_root, diff_id)

    # paper.tex must still be untouched
    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_after == sha


# ---------------------------------------------------------------------------
# T5: UserDenied — user types 'n'
# ---------------------------------------------------------------------------

def test_t5_user_denied(paper_root, capsys):
    """Gate 5: edit_gate() raises UserDenied when user answers 'n'.

    Mocks _is_real_tty() and _read_tty_answer() to simulate user declining.
    Verifies that _print_colored_diff_full output was emitted (diff shown before prompt).
    """
    from paper_agent.core.edit_gate import edit_gate, UserDenied

    adv = _make_advisory(paper_root)
    paper_tex = paper_root / "src" / "paper.tex"
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    with mock.patch("paper_agent.core.edit_gate._is_real_tty", return_value=True):
        with mock.patch("paper_agent.core.edit_gate._read_tty_answer", return_value="n"):
            with pytest.raises(UserDenied):
                edit_gate(paper_root, adv["diff_id"])

    # Diff was printed (captured by capsys)
    captured = capsys.readouterr()
    assert "@@" in captured.out or "---" in captured.out, (
        "Expected diff output before user prompt"
    )

    # paper.tex must be untouched
    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_before == sha_after


# ---------------------------------------------------------------------------
# T6: Concurrent lock — second process cannot acquire lock while first holds it
# ---------------------------------------------------------------------------

def test_t6_concurrent_lock_blocked(paper_root):
    """Gate 3: A second process cannot acquire lock while edit_gate() holds it.

    Starts a subprocess that acquires the exclusive lock on paper.tex,
    then verifies that _acquire_exclusive_lock() raises BlockingIOError
    in the current process.
    """
    from paper_agent.core.edit_gate import _acquire_exclusive_lock

    paper_tex = paper_root / "src" / "paper.tex"

    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}

    # Spawn a holder process that acquires lock and signals via stdout
    holder_script = (
        "import sys, time\n"
        f"sys.path.insert(0, r'{SRC_ROOT}')\n"
        "from paper_agent.core.edit_gate import _acquire_exclusive_lock\n"
        f"f = open(r'{paper_tex}', 'r+b')\n"
        "_acquire_exclusive_lock(f)\n"
        "print('GOT LOCK', flush=True)\n"
        "time.sleep(5)\n"
    )

    try:
        holder = subprocess.Popen(
            [sys.executable, "-c", holder_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
    except PermissionError as e:
        pytest.skip(f"subprocess not permitted in this environment: {e}")

    try:
        # Wait for holder to signal it has the lock
        output = holder.stdout.readline()
        assert "GOT LOCK" in output, f"Holder failed to acquire lock: {output!r}"

        # Now try to acquire lock in this process — must fail
        with open(paper_tex, "r+b") as f:
            with pytest.raises(BlockingIOError):
                _acquire_exclusive_lock(f)

    finally:
        holder.terminate()
        holder.wait(timeout=5)

    # After holder terminates, lock should be releasable
    with open(paper_tex, "r+b") as f:
        _acquire_exclusive_lock(f)
        # Lock released on with exit


# ---------------------------------------------------------------------------
# T3a: stdin pipe spoofing — attacker pre-feeds "y\n" through pipe
# ---------------------------------------------------------------------------

def test_t3a_stdin_pipe_spoofing_blocked(paper_root):
    """Gate 1 (plan-original T3): LLM agent cannot bypass TTY guard by piping fake "y" to stdin.

    Threat model: an LLM agent in the same process / a wrapper subprocess
    pre-feeds "y\\n" through stdin pipe hoping to satisfy the TTY confirm prompt.
    The TTY guard (_is_real_tty: stdin.isatty() AND stdout.isatty()) must return
    False because pipe-fed stdin is not a TTY → NonInteractiveSession raised
    BEFORE prompt is reached, no matter what the pipe contains.

    Run in a subprocess with stdin=PIPE to faithfully reproduce the attack
    (in-process mocking can't simulate the OS-level pipe spoof).
    """
    adv = _make_advisory(paper_root)
    paper_tex = paper_root / "src" / "paper.tex"
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()

    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT), "PYTHONIOENCODING": "utf-8"}

    attack_script = (
        "import sys\n"
        f"sys.path.insert(0, r'{SRC_ROOT}')\n"
        "from paper_agent.core.edit_gate import edit_gate, NonInteractiveSession\n"
        "try:\n"
        f"    edit_gate(r'{paper_root}', '{adv['diff_id']}')\n"
        "    print('LEAKED:edit_gate returned without raising', flush=True)\n"
        "    sys.exit(99)\n"
        "except NonInteractiveSession:\n"
        "    print('BLOCKED:NonInteractiveSession', flush=True)\n"
        "    sys.exit(0)\n"
        "except Exception as e:\n"
        "    print(f'OTHER:{type(e).__name__}:{e}', flush=True)\n"
        "    sys.exit(1)\n"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", attack_script],
            input="y\n",
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
    except PermissionError as e:
        # Sandbox env without subprocess permission (WinError 5) — skip, not fail
        pytest.skip(f"subprocess not permitted in this environment: {e}")

    # 1. Must exit 0 (NonInteractiveSession raised — attack blocked)
    assert proc.returncode == 0, (
        f"TTY guard bypassed by stdin pipe spoof.\n"
        f"  exit={proc.returncode}\n"
        f"  stdout={proc.stdout!r}\n"
        f"  stderr={proc.stderr!r}"
    )
    # 2. Must report BLOCKED, never LEAKED
    assert "BLOCKED:NonInteractiveSession" in proc.stdout, (
        f"Expected BLOCKED:NonInteractiveSession, got: {proc.stdout!r}"
    )
    assert "LEAKED" not in proc.stdout, "edit_gate silently accepted piped 'y' — L-033 violation"

    # 3. paper.tex untouched (the gate must abort BEFORE touching anything)
    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_after == sha_before, "paper.tex was modified despite TTY guard"
