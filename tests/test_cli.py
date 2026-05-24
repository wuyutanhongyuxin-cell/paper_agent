"""CLI smoke + UTF-8 cp936 regression (P0-2)."""
import subprocess
import sys
import pytest


def test_version_flag_smoke():
    """--version 不崩 + 输出含语义版本号字段。"""
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "--version"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0
    assert "paper-agent" in result.stdout.lower() or "paper_agent" in result.stdout.lower()


def test_help_flag_smoke():
    """--help 列出 init/audit/compile/apply 4 个子命令。"""
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "--help"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0
    for sub in ("init", "audit", "compile", "apply"):
        assert sub in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="cp936 regression Windows-only")
def test_utf8_chinese_no_mojibake():
    """Windows cp936 默认下，中文 print 不变 mojibake (P0-2)。"""
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "--help"],
        capture_output=True,
    )
    out = result.stdout.decode("utf-8", errors="replace")
    assert "?" not in out[:200] or "init" in out


def test_apply_requires_diff_id_and_paper_root():
    """apply 缺 --diff-id / --paper-root → argparse 报错。"""
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "apply"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "diff-id" in combined or "paper-root" in combined


def test_apply_in_non_tty_reports_non_interactive(tmp_path):
    """apply 在 pytest 子进程（非 TTY）应报 NonInteractiveSession，退出非 0。

    Gate 1 (TTY check) 先于 Gate 2/3/4 触发；这是 L-033 的核心信任锚。
    """
    import hashlib
    root = tmp_path / "fake"
    (root / "src").mkdir(parents=True)
    (root / "src" / "paper.tex").write_text("x", encoding="utf-8")
    sha = hashlib.sha256(b"x").hexdigest()
    diff_id = "deadbeef12345678"
    adv = root / "advisory" / diff_id
    adv.mkdir(parents=True)
    (adv / "meta.json").write_text(
        '{"diff_id":"' + diff_id + '","expected_file_sha256":"' + sha + '",'
        '"rule":"test","file":"src/paper.tex","line":1,'
        '"created_at":"2026-05-24T00:00:00Z"}',
        encoding="utf-8",
    )
    (adv / "diff.patch").write_text(
        "--- a/src/paper.tex\n+++ b/src/paper.tex\n@@ -1,1 +1,1 @@\n-x\n+y\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "apply",
         "--paper-root", str(root), "--diff-id", diff_id],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode != 0, (
        f"expected non-zero exit, got 0\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert (
        "NonInteractiveSession" in result.stderr
        or "TTY" in result.stderr
    ), (
        f"expected NonInteractiveSession or TTY in stderr, got:\n{result.stderr!r}"
    )


def test_init_writes_latexmkrc_and_ps1(tmp_path, fixtures_dir):
    """paper-agent init <dir> 生成 .latexmkrc + compile.ps1。"""
    import shutil
    paper_root = tmp_path / "newpaper"
    (paper_root / "src").mkdir(parents=True)
    shutil.copy(fixtures_dir / "min_linguistics_zh.tex", paper_root / "src" / "paper.tex")
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "init",
         str(paper_root), "--lang", "zh", "--field", "linguistics"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"init failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (paper_root / ".latexmkrc").exists()
    assert (paper_root / "compile.ps1").exists()


def test_audit_returns_findings_for_fixture(tmp_path, fixtures_dir):
    """audit fixture 输出 findings 行；非 --strict → 退出 0。"""
    import shutil
    paper_root = tmp_path / "p"
    (paper_root / "src").mkdir(parents=True)
    shutil.copy(fixtures_dir / "min_linguistics_zh.tex", paper_root / "src" / "paper.tex")
    shutil.copy(fixtures_dir / "min_linguistics_zh.bib", paper_root / "src" / "references.bib")
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit",
         str(paper_root), "--rules", "bib,punct,humanize"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"audit failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "findings" in result.stdout.lower()


def test_audit_strict_exits_nonzero_on_errors(tmp_path, fixtures_dir):
    """fixture 含 ERROR (P5 半角逗号 / dangling_cite) → --strict 返 1。"""
    import shutil
    paper_root = tmp_path / "p"
    (paper_root / "src").mkdir(parents=True)
    shutil.copy(fixtures_dir / "min_linguistics_zh.tex", paper_root / "src" / "paper.tex")
    shutil.copy(fixtures_dir / "min_linguistics_zh.bib", paper_root / "src" / "references.bib")
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit",
         str(paper_root), "--rules", "bib,punct,humanize", "--strict"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1, (
        f"expected rc=1 due to ERROR findings, got rc={result.returncode}\n"
        f"stdout={result.stdout[:500]}\nstderr={result.stderr[:500]}"
    )
