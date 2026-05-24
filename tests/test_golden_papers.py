"""5 个学科 fixture 跑 audit 应 0 ERROR (合规版作 baseline)。"""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("field", ["medicine", "humanities", "cs", "sciences"])
def test_field_fixture_compliant(tmp_path, fixtures_dir, field):
    import shutil
    root = tmp_path / field
    (root / "src").mkdir(parents=True)
    shutil.copy(fixtures_dir / f"min_{field}_zh.tex", root / "src" / "paper.tex")
    shutil.copy(fixtures_dir / f"min_{field}_zh.bib", root / "src" / "references.bib")
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit",
         str(root), "--rules", "bib,punct,humanize", "--strict"],
        capture_output=True, text=True, encoding="utf-8",
    )
    # 合规 fixture → --strict 通过
    assert result.returncode == 0, (
        f"{field} fixture has ERROR findings:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cp936_regression_chinese_not_mojibake(tmp_path, fixtures_dir):
    """Windows 默认 cp936，paper.tex 含中文 + 千分位 + p 值 → audit 不崩 + 不报"千分位被全角化"。"""
    import shutil
    root = tmp_path / "cp936"
    (root / "src").mkdir(parents=True)
    shutil.copy(fixtures_dir / "cp936_regression.tex", root / "src" / "paper.tex")
    (root / "src" / "references.bib").write_text("", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit",
         str(root), "--rules", "punct,humanize"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"cp936 audit failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "R6" not in result.stdout, (
        f"1,818,649 半角千分位应合规，但报了 R6:\n{result.stdout}"
    )
