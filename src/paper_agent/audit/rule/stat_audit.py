"""
stat_audit.py —— 统计报告格式审计（spec §D.2 stat_audit / 0.1.1 M-B.2）

四类检查，所有都按"段内同段"语境判定，避免跨段误报：

  1. p_value_out_of_range     ERROR  `p = X` / `p < X` / `p > X` 中 X ∉ [0, 1]
  2. anova_missing_F/df/p     WARN   ANOVA 块（含 'ANOVA' 或 'F(' 关键词）缺 F/df/p 之一
  3. anova_missing_eta_or_N   INFO   ANOVA 块缺 η²/η_p²/η²_p（效应量）或 N（样本量）
  4. mean_missing_sd_or_n     WARN   段含 mean/M/均值 但同段缺 SD/std/N
  5. ci_missing_bounds        WARN   段含 'CI' 或 '置信区间' 但无 `[lo, hi]` 形式

设计动机：
  reverse_verify 检测的是"特定数字是否出现"，stat_audit 检测的是"统计报告格式
  完整性"。两者正交：reverse_verify 知道答案，stat_audit 不知道答案但能查
  APA-style 完整性。

使用：
  python -m paper_agent.audit.rule.stat_audit --tex <path> --out <path.json>

退出码：0 全部通过 / 1 有 ERROR-级 finding / 2 tex 文件不存在

通用化（spec §A.3）：
  - 路径 CLI 参数化（--tex 必填）
  - 关键词支持中英双语（mean/均值、SD/标准差、CI/置信区间）
  - 不 hardcode 学科特异统计量（无 BCC / 失语症 等）
  - 输出 schema 中性

注意：本 rule 与失语症 paper 王老师 hard constraint "ANOVA 三个 p > 0.10" 不冲突：
  - 王老师约束是 p 值 **数值** 必须 > 0.10（保证两因素无交互效应）
  - stat_audit 约束是 p 值 **格式** ∈ [0, 1]（数学合法性）
  - 两者正交，且 0.10 ∈ [0, 1] 始终通过 stat_audit

L-033 合规：只读 paper.tex，只写 audit 报告（.json）；不动 paper.tex 字节。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from paper_agent._util import reconfigure_utf8


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

COMMENT_RE = re.compile(r"(?<!\\)%.*$")

# 提取 p 值：p = / p < / p > 后跟数（含科学计数法）
# 使用 \b 避免误抓 "sp = 5"; 允许 LaTeX 数学环境 $<$, $>$, $=$
P_VALUE_RE = re.compile(
    r"(?<![A-Za-z\\])"               # 前不接字母 / 反斜杠（排除 \p, sp, np, top, group 等）
    r"[pP]"                          # p 或 P
    r"\s*"
    r"(?:\$?\s*([=<>])\s*\$?)"       # 关系符号 = < >, 可被 LaTeX $...$ 包
    r"\s*"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"  # 数值：可负 / 整数 / 小数 / 科学计数法
)

# ANOVA 块关键词：'ANOVA' 或 'F(d, d)' pattern
ANOVA_KEYWORD_RE = re.compile(r"ANOVA|anova|F\s*\(\s*\d+", re.IGNORECASE)

# F 值检测：F = X 或 F(df1, df2) = X
F_VALUE_RE = re.compile(r"\bF\s*(?:\(\s*\d[^)]*\))?\s*=\s*\d", re.IGNORECASE)

# df 检测：df = N, 或 F(df1, df2) 形式（df 隐含在括号里）
DF_RE = re.compile(r"\bdf\s*=|F\s*\(\s*\d+\s*,\s*\d+\s*\)", re.IGNORECASE)

# p 检测（同 P_VALUE_RE 简化版）：仅查 'p' 后跟 = / < / >
P_PRESENT_RE = re.compile(
    r"(?<![A-Za-z\\])[pP]\s*(?:\$?\s*[=<>]\s*\$?)\s*\d"
)

# 效应量：η² / η_p² / partial η² / eta-squared / Cohen d / Cohen's d / r=
ETA_RE = re.compile(
    r"η\^?2|η²|η_?p\^?2|η_?p²|partial\s+eta|eta[\-\s]?squared|Cohen('?s)?\s*d|\\eta",
    re.IGNORECASE,
)

# N（样本量）：N = X 或 n = X
N_RE = re.compile(r"\b[Nn]\s*=\s*\d+")

# 描述统计 mean：M = X / mean = X / 均值
MEAN_RE = re.compile(r"\bM\s*=\s*\d|mean\s*=|均值|\bmean\b", re.IGNORECASE)

# SD / 标准差
SD_RE = re.compile(r"\bSD\s*=|\bstd\s*=|标准差|\bSD\b", re.IGNORECASE)

# CI 关键词
CI_KEYWORD_RE = re.compile(r"\bCI\b|置信区间")

# [lo, hi] 形式：方括号内含逗号分隔两数
CI_BOUNDS_RE = re.compile(r"\[\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*\]")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def strip_tex_comments(text: str) -> str:
    return "\n".join(COMMENT_RE.sub("", line) for line in text.splitlines())


def _line_no(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def extract_p_values(text: str) -> list[tuple[str, float, int]]:
    """Return [(op, value, line_no), ...] for all p-value occurrences.

    op ∈ {'=', '<', '>'}; line_no is 1-indexed.
    """
    results = []
    for m in P_VALUE_RE.finditer(text):
        op = m.group(1)
        try:
            v = float(m.group(2))
        except ValueError:
            continue
        line = _line_no(text, m.start())
        results.append((op, v, line))
    return results


def _split_paragraphs(text: str) -> list[tuple[str, int]]:
    """Blank-line-separated paragraphs; returns [(text, start_line), ...]."""
    out = []
    cur, start = [], 1
    for i, line in enumerate(text.splitlines(), start=1):
        if line.strip() == "":
            if cur:
                out.append(("\n".join(cur), start))
                cur = []
            start = i + 1
        else:
            if not cur:
                start = i
            cur.append(line)
    if cur:
        out.append(("\n".join(cur), start))
    return out


def find_anova_blocks(text: str) -> list[dict]:
    """Return [{text, line}] for paragraphs containing ANOVA keywords."""
    blocks = []
    for para_text, start_line in _split_paragraphs(text):
        if ANOVA_KEYWORD_RE.search(para_text):
            blocks.append({"text": para_text, "line": start_line})
    return blocks


def has_descriptive_stats_complete(paragraph: str) -> bool:
    """段含 mean/M= → 必须同段含 SD/标准差; 否则不完整。无 mean → trivially 完整。

    APA 规范: 报告 mean 必须同时报 SD（描述统计完整性的核心）。N 在 method 段
    通常已说过，不强求每个 mean 后跟 N。
    """
    if not MEAN_RE.search(paragraph):
        return True
    return bool(SD_RE.search(paragraph))


def has_ci_bounds(paragraph: str) -> bool:
    """段含 CI 关键词 → 必须含 [lo, hi]；否则不完整。无 CI → trivially 完整。"""
    if not CI_KEYWORD_RE.search(paragraph):
        return True
    return bool(CI_BOUNDS_RE.search(paragraph))


# ---------------------------------------------------------------------------
# Audit core
# ---------------------------------------------------------------------------

def run_audit(tex_path: Path) -> tuple[dict, list[dict]]:
    text_raw = tex_path.read_text(encoding="utf-8")
    text = strip_tex_comments(text_raw)

    findings: list[dict] = []

    # Rule 1: p_value_out_of_range
    p_values = extract_p_values(text)
    for op, v, line in p_values:
        if v < 0 or v > 1:
            findings.append({
                "severity": "ERROR",
                "rule": "p_value_out_of_range",
                "type": "p_value_out_of_range",
                "file": str(tex_path),
                "line": line,
                "col": None,
                "message": f"p {op} {v} 超出 [0, 1] 区间",
                "p_value": v,
                "operator": op,
                "suggested_fix": None,
            })

    # Rule 2 / 3: ANOVA completeness
    for block in find_anova_blocks(text):
        body = block["text"]
        line = block["line"]
        missing_F = not F_VALUE_RE.search(body)
        missing_df = not DF_RE.search(body)
        missing_p = not P_PRESENT_RE.search(body)
        missing_eta = not ETA_RE.search(body)
        missing_N = not N_RE.search(body)

        if missing_F:
            findings.append({
                "severity": "WARN",
                "rule": "anova_missing_F",
                "type": "anova_missing_F",
                "file": str(tex_path), "line": line, "col": None,
                "message": f"ANOVA 块缺 F 值报告 (L{line})",
                "suggested_fix": None,
            })
        if missing_df:
            findings.append({
                "severity": "WARN",
                "rule": "anova_missing_df",
                "type": "anova_missing_df",
                "file": str(tex_path), "line": line, "col": None,
                "message": f"ANOVA 块缺 df 报告 (L{line})",
                "suggested_fix": None,
            })
        if missing_p:
            findings.append({
                "severity": "WARN",
                "rule": "anova_missing_p",
                "type": "anova_missing_p",
                "file": str(tex_path), "line": line, "col": None,
                "message": f"ANOVA 块缺 p 值报告 (L{line})",
                "suggested_fix": None,
            })
        if missing_eta:
            findings.append({
                "severity": "INFO",
                "rule": "anova_missing_eta",
                "type": "anova_missing_eta",
                "file": str(tex_path), "line": line, "col": None,
                "message": f"ANOVA 块缺效应量报告（η²/Cohen d 等，L{line}）",
                "suggested_fix": None,
            })
        if missing_N:
            findings.append({
                "severity": "INFO",
                "rule": "anova_missing_N",
                "type": "anova_missing_N",
                "file": str(tex_path), "line": line, "col": None,
                "message": f"ANOVA 块缺样本量 N 报告 (L{line})",
                "suggested_fix": None,
            })

    # Rule 4: descriptive stats completeness
    for para_text, start_line in _split_paragraphs(text):
        if not has_descriptive_stats_complete(para_text):
            findings.append({
                "severity": "WARN",
                "rule": "mean_missing_sd_or_n",
                "type": "mean_missing_sd_or_n",
                "file": str(tex_path), "line": start_line, "col": None,
                "message": (
                    f"描述统计段含 mean/M 但缺 SD/N (L{start_line})"
                ),
                "suggested_fix": None,
            })

    # Rule 5: CI bounds
    for para_text, start_line in _split_paragraphs(text):
        if not has_ci_bounds(para_text):
            findings.append({
                "severity": "WARN",
                "rule": "ci_missing_bounds",
                "type": "ci_missing_bounds",
                "file": str(tex_path), "line": start_line, "col": None,
                "message": (
                    f"段含 CI/置信区间 但缺 [lo, hi] 形式 (L{start_line})"
                ),
                "suggested_fix": None,
            })

    summary = {
        "p_value_count": len(p_values),
        "p_value_out_of_range_count": sum(
            1 for f in findings if f["rule"] == "p_value_out_of_range"
        ),
        "anova_block_count": len(find_anova_blocks(text)),
        "anova_missing_total": sum(
            1 for f in findings if f["rule"].startswith("anova_missing_")
        ),
        "mean_missing_sd_or_n_count": sum(
            1 for f in findings if f["rule"] == "mean_missing_sd_or_n"
        ),
        "ci_missing_bounds_count": sum(
            1 for f in findings if f["rule"] == "ci_missing_bounds"
        ),
    }
    return summary, findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    reconfigure_utf8()
    ap = argparse.ArgumentParser(
        prog="paper_agent.audit.rule.stat_audit",
        description="统计报告格式审计：p ∈ [0,1] + ANOVA 五件套 + 描述统计 + CI 区间",
    )
    ap.add_argument("--tex", type=Path, required=True, help="paper.tex 路径")
    ap.add_argument(
        "--lang", default="zh", choices=["zh", "en", "ja"],
        help="语言标签（informational only）",
    )
    ap.add_argument("--out", type=Path, default=None, help="JSON 输出路径")
    args = ap.parse_args()

    if not args.tex.exists():
        print(f"[FAIL] tex not found: {args.tex}", file=sys.stderr)
        return 2

    summary, findings = run_audit(args.tex)

    audit_id = f"stat-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if args.out is not None:
        out_json = args.out
    else:
        out_dir = Path.cwd() / "audit"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir / f"stat_audit_{datetime.now().strftime('%Y%m%d')}.json"

    out_json.parent.mkdir(parents=True, exist_ok=True)
    json_obj = {
        "audit_id": audit_id,
        "tex": str(args.tex),
        "lang": args.lang,
        "summary": summary,
        "findings": findings,
    }
    out_json.write_text(json.dumps(json_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[报告] json -> {out_json}")

    print(f"[stat_audit] tex: {args.tex}")
    print(
        f"[size] p_values={summary['p_value_count']} "
        f"anova_blocks={summary['anova_block_count']}"
    )
    print()

    error_count = sum(1 for f in findings if f["severity"] == "ERROR")
    warn_count = sum(1 for f in findings if f["severity"] == "WARN")
    info_count = sum(1 for f in findings if f["severity"] == "INFO")

    for f in findings[:30]:
        sev = f["severity"]
        tag = {"ERROR": "FAIL", "WARN": "WARN", "INFO": "INFO"}[sev]
        line_label = f" L{f['line']}" if f.get("line") else ""
        print(f"[{tag}]{line_label} {f['rule']}: {f['message']}")

    print()
    if error_count == 0 and warn_count == 0 and info_count == 0:
        print("[PASS] stat_audit 全部通过")
    else:
        print(
            f"[stat_audit] ERROR={error_count} WARN={warn_count} INFO={info_count}"
        )

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
