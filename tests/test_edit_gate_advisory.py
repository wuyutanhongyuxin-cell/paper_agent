"""Edit Gate Layer 1 (audit) + Layer 2 (advisory) — read-only。

spec §D.1：audit() 跑规则返 finding；advisory() 写 advisory/<diff_id>/，不动 paper.tex。
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def paper_root(tmp_path, fixtures_dir):
    """复制 fixture 到 tmp_path/paper/ 模拟一个 paper-root。"""
    root = tmp_path / "paper"
    (root / "src").mkdir(parents=True)
    shutil.copy(fixtures_dir / "min_linguistics_zh.tex", root / "src" / "paper.tex")
    shutil.copy(fixtures_dir / "min_linguistics_zh.bib", root / "src" / "references.bib")
    return root


def test_audit_returns_findings_does_not_write(paper_root):
    """Layer 1：audit 只读，paper.tex sha256 前后不变。"""
    from paper_agent.core.edit_gate import audit

    paper_tex = paper_root / "src" / "paper.tex"
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    findings = audit(paper_root, rules=["punct", "bib", "humanize"], lang="zh")
    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_before == sha_after, "audit 改了 paper.tex —— L-033 违反"
    assert isinstance(findings, list)
    assert len(findings) > 0, "fixture 有违例，应该有 findings"


def test_advisory_writes_to_advisory_dir_only(paper_root):
    """Layer 2：advisory 写 advisory/<diff_id>/{meta.json,before.txt,after.txt,diff.patch}；paper.tex 不变。"""
    from paper_agent.core.edit_gate import advisory

    paper_tex = paper_root / "src" / "paper.tex"
    sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    patches = advisory(paper_root, rules=["punct"], lang="zh")
    sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    assert sha_before == sha_after

    advisory_dir = paper_root / "advisory"
    assert advisory_dir.is_dir()
    diff_ids = [p.name for p in advisory_dir.iterdir() if p.is_dir()]
    assert len(diff_ids) >= 1

    for diff_id in diff_ids:
        d = advisory_dir / diff_id
        assert (d / "meta.json").exists()
        assert (d / "before.txt").exists()
        assert (d / "after.txt").exists()
        assert (d / "diff.patch").exists()
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert "expected_file_sha256" in meta
        assert meta["expected_file_sha256"] == sha_before
        assert "created_at" in meta
        assert "diff_id" in meta


def test_advisory_diff_id_is_deterministic_for_same_input(paper_root):
    """同 paper.tex + 同 rule → 同 diff_id（便于追踪）。"""
    from paper_agent.core.edit_gate import advisory

    p1 = advisory(paper_root, rules=["punct"], lang="zh")
    shutil.rmtree(paper_root / "advisory")
    p2 = advisory(paper_root, rules=["punct"], lang="zh")
    ids1 = sorted([p["diff_id"] for p in p1])
    ids2 = sorted([p["diff_id"] for p in p2])
    assert ids1 == ids2
