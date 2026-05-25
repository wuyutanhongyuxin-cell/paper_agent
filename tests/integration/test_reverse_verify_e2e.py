"""reverse_verify (number rule) e2e — M-A reverse_verify 通用化抽出。

覆盖：
  - truth.json 缺失 → audit() silently skip（通用化考虑，不是所有 paper 都有真值表）
  - truth.json 存在 + 全 hit → 0 number_miss findings
  - truth.json 含 miss 项 → 1 ERROR finding
  - L-033 read-only：truth.json + paper.tex 字节级不可变动
  - paper-agent audit --rules number 单独跑 number rule
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "non_aphasia_cs"


def _run_audit(work: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "audit", str(work),
         "--lang", "zh", *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _write_truth(work: Path, items: list[dict]) -> Path:
    truth = {
        "version": "0.1.1",
        "paper": {"id": "test", "title": "e2e fixture"},
        "items": items,
    }
    p = work / "truth.json"
    p.write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    return p


def test_audit_skips_number_when_truth_json_missing(tmp_path):
    """通用化考虑：truth.json 不存在 → number rule silently skip 不报错。

    回归保护 paper-agent paper-agnostic 承诺：cs fixture 没 truth.json，
    应该按默认 4 rule 跑但 number rule 跳过，不出 ERROR。
    """
    work = tmp_path / "no_truth"
    shutil.copytree(FIXTURE, work)
    assert not (work / "truth.json").exists()

    result = _run_audit(work)
    assert result.returncode == 0, (
        f"audit failed when truth.json missing: rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "0 findings (0 ERROR)" in result.stdout
    # 不应该出现 number_miss
    assert "number_miss" not in result.stdout


def test_audit_number_rule_zero_miss(tmp_path):
    """truth.json 全部命中 → 0 number_miss findings + audit 整体 0 findings 0 ERROR。"""
    work = tmp_path / "with_truth_clean"
    shutil.copytree(FIXTURE, work)

    paper_tex = work / "src" / "paper.tex"
    body = paper_tex.read_text(encoding="utf-8")
    # cs fixture 真实含的数字：从 paper.tex 抓两个真实数字回填 truth
    # （fixture 是 HNSW vs IVF-PQ 实证比较，含数字）
    assert "HNSW" in body or "IVF" in body  # 防 fixture 改了
    # 用一个肯定在 fixture 的 token 做 truth
    _write_truth(work, [
        {"name": "method name 1", "candidates": ["HNSW"]},
    ])

    result = _run_audit(work)
    assert result.returncode == 0, f"rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    assert "number_miss" not in result.stdout
    assert "0 findings (0 ERROR)" in result.stdout


def test_audit_number_rule_one_miss_returns_error(tmp_path):
    """truth.json 含 miss 项 → 1 ERROR number_miss finding；--strict 时 rc=1。"""
    work = tmp_path / "with_truth_miss"
    shutil.copytree(FIXTURE, work)
    _write_truth(work, [
        {"name": "missing value", "candidates": ["__definitely_not_in_paper_tex_42__"]},
    ])

    result = _run_audit(work, "--strict")
    # number_miss 是 ERROR → --strict 必返 1
    assert result.returncode == 1, (
        f"--strict should fail on number_miss: rc={result.returncode}\n{result.stdout}"
    )
    assert "number_miss" in result.stdout
    assert "missing value" in result.stdout


def test_audit_number_rule_isolated_via_rules_flag(tmp_path):
    """paper-agent audit --rules number 单独跑 number rule（不跑 bib/punct/humanize）。"""
    work = tmp_path / "rules_number_only"
    shutil.copytree(FIXTURE, work)
    _write_truth(work, [
        {"name": "method", "candidates": ["HNSW"]},
    ])

    result = _run_audit(work, "--rules", "number")
    assert result.returncode == 0
    # 应该只跑 number → 0 findings + 没有 punct/humanize/bib finding
    assert "0 findings (0 ERROR)" in result.stdout


def test_audit_number_rule_is_read_only(tmp_path):
    """L-033：跑 number rule 前后 paper.tex + truth.json 字节级不变。"""
    work = tmp_path / "read_only"
    shutil.copytree(FIXTURE, work)
    truth_path = _write_truth(work, [
        {"name": "method", "candidates": ["HNSW"]},
        {"name": "missing", "candidates": ["__nope__"]},  # 故意 miss 一项触发 finding
    ])

    paper_tex = work / "src" / "paper.tex"
    paper_sha_before = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    truth_sha_before = hashlib.sha256(truth_path.read_bytes()).hexdigest()

    result = _run_audit(work, "--rules", "number")
    assert result.returncode == 0  # 非 --strict, miss 不 fail

    paper_sha_after = hashlib.sha256(paper_tex.read_bytes()).hexdigest()
    truth_sha_after = hashlib.sha256(truth_path.read_bytes()).hexdigest()
    assert paper_sha_before == paper_sha_after, "audit 改了 paper.tex 字节 — 违反 L-033"
    assert truth_sha_before == truth_sha_after, "audit 改了 truth.json 字节 — 违反 L-033"
