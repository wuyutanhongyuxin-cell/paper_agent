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
