"""
reverse_verify.py —— 通用化"真值反推"审计（spec §C.2 / 0.1.1 路线图）

输入 paper.tex + truth.json（项目级真值表），断言**真值表里每一项必须在
paper.tex 正文中出现**。任一 miss → ERROR finding。所有 hit → [PASS]。

设计动机：
  weiwuer/paper/tools/number_audit.py 把 28 项失语症 paper 的真值（BCC 词频 /
  ANOVA p / cell mean / Xu & Li 词典规模等）硬编码在源里——违反 paper-agent
  长期通用化承诺（[[feedback_paper_agent_long_term_generality]]）。
  本模块把 TRUTH dict 抽到外部 JSON 配置：paper-agent 引擎完全 paper-agnostic，
  每个 paper 在自己的 paper_root/truth.json 里列自己的关键真值即可。

使用：
  python -m paper_agent.audit.rule.reverse_verify --tex <path> --truth <path> --out <path.json>
  python -m paper_agent.audit.rule.reverse_verify --tex <path> --truth <path> --lang zh --out <path.json>

退出码：0 全部命中 / 1 有 ERROR-级 finding / 2 文件不存在

truth.json schema：
  {
    "version": "0.1.1",
    "paper": {                          # optional metadata, 不参与匹配
      "id": "aphasia-zh-0.1.0",
      "title": "...",
      "note": "..."
    },
    "items": [
      {
        "name": "BCC 原始词数",          # required, 描述性中性字符串
        "section": "§3.1 词频基线",     # optional, informational only
        "severity": "ERROR",             # optional, 默认 ERROR (允许 ERROR/WARN/INFO)
        "candidates": [                  # required, 至少 1 个字面字符串
          "1,818,649", "1818649", "1{,}818{,}649"
        ],
        "note": "..."                    # optional, 给 reviewer 的说明
      }
    ]
  }

匹配语义（与 number_audit.py 等价，保留向后兼容）：
  - 读 paper.tex (utf-8)
  - 行级剥除 %-注释（保留行号）：(?<!\\)%.*$ → 空
  - 对每个 item：hit = any(c in body for c in candidates)
  - miss → 1 个 Finding(severity=item["severity"] or "ERROR",
                        rule="number_miss",
                        file=tex_path,
                        line=0,                     # paper 全文反推，不指向行
                        message="'{name}' (§{section}) not found; candidates: {...}")

L-033 合规：本工具只读 .tex / .truth.json，只写 audit 报告（.json）；
不动 paper.tex / truth.json 任何字节。

通用化（spec §A.3 第五原则）：
  - 所有路径 CLI 参数化（--tex / --truth 必填，--out 可选）
  - 输出 schema 字段名中性（finding / severity / rule / candidates）
  - 引擎不识别学科特异规则（不假设是 BCC / ANOVA / 词典规模）
  - 学科特异真值归 <paper_root>/truth.json 各 paper 自管
  - lang 参数当前**informational only**（候选字符串是字面字面量，与语言无关；
    保留接口为 0.2.0+ 加入 lang-aware 候选生成器预留）

向后兼容：
  weiwuer/paper/tools/number_audit.py 同等 28 项真值迁出到
  weiwuer/paper/truth.json 后，运行
    paper-agent audit weiwuer/paper --rules number
  应输出 [PASS] 数字反推 100% 命中，与旧工具等价。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from paper_agent._util import reconfigure_utf8


# 行级 %-注释剥除（保留行号 / 不处理 \% 转义百分号）
# 与 weiwuer/paper/tools/number_audit.py L44-49 等价
COMMENT_RE = re.compile(r"(?<!\\)%.*$")

# Severity 白名单（与 core/edit_gate.py Finding.severity 注释一致）
VALID_SEVERITY = {"ERROR", "WARN", "INFO"}


def strip_tex_comments(text: str) -> str:
    """剥除 LaTeX 行级 %-注释，保留行号。\\% 字面转义百分号保留。"""
    return "\n".join(COMMENT_RE.sub("", line) for line in text.splitlines())


def load_truth(truth_path: Path) -> dict:
    """读 truth.json，做基础 schema 校验。"""
    if not truth_path.exists():
        raise FileNotFoundError(f"truth file not found: {truth_path}")
    data = json.loads(truth_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"truth.json must be a dict, got {type(data).__name__}")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("truth.json missing 'items' list")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] must be a dict")
        if not isinstance(item.get("name"), str) or not item["name"]:
            raise ValueError(f"items[{i}] missing 'name' (non-empty string)")
        cands = item.get("candidates")
        if not isinstance(cands, list) or not cands:
            raise ValueError(f"items[{i}] '{item['name']}' missing 'candidates' (non-empty list)")
        for j, c in enumerate(cands):
            if not isinstance(c, str) or not c:
                raise ValueError(
                    f"items[{i}] '{item['name']}' candidates[{j}] must be a non-empty string"
                )
        sev = item.get("severity", "ERROR")
        if sev not in VALID_SEVERITY:
            raise ValueError(
                f"items[{i}] '{item['name']}' severity={sev!r} not in {sorted(VALID_SEVERITY)}"
            )
    return data


def run_audit(tex_path: Path, truth_path: Path) -> tuple[dict, list[dict]]:
    """跑反推审计。返回 (summary, findings)."""
    truth = load_truth(truth_path)
    items = truth["items"]

    text = tex_path.read_text(encoding="utf-8")
    body = strip_tex_comments(text)

    findings: list[dict] = []
    hit_count = 0
    for item in items:
        name = item["name"]
        section = item.get("section", "")
        candidates = item["candidates"]
        severity = item.get("severity", "ERROR")

        hit = any(c in body for c in candidates)
        if hit:
            hit_count += 1
            continue

        section_label = f" (§{section})" if section else ""
        message = (
            f"'{name}'{section_label} not found in paper body; "
            f"candidates: {candidates}"
        )
        findings.append({
            "severity": severity,
            "rule": "number_miss",
            "type": "number_miss",       # 兼容 _normalize_finding 的两个 discriminator
            "file": str(tex_path),
            "line": 0,
            "col": None,
            "message": message,
            "name": name,
            "section": section,
            "candidates": candidates,
            "note": item.get("note", ""),
            "suggested_fix": None,
        })

    summary = {
        "total": len(items),
        "hit": hit_count,
        "miss": len(items) - hit_count,
        "paper": truth.get("paper", {}),
        "truth_version": truth.get("version", "unknown"),
    }
    return summary, findings


def main() -> int:
    reconfigure_utf8()
    ap = argparse.ArgumentParser(
        prog="paper_agent.audit.rule.reverse_verify",
        description="通用化真值反推审计：断言 truth.json 每项必须在 paper.tex 正文出现。",
    )
    ap.add_argument("--tex", type=Path, required=True, help="paper.tex 路径")
    ap.add_argument("--truth", type=Path, required=True, help="truth.json 路径")
    ap.add_argument(
        "--lang",
        default="zh",
        choices=["zh", "en", "ja"],
        help="语言标签（当前 informational only，0.2.0+ 预留接口）",
    )
    ap.add_argument("--out", type=Path, default=None, help="JSON 输出路径（默认写 audit/）")
    args = ap.parse_args()

    if not args.tex.exists():
        print(f"[FAIL] tex not found: {args.tex}", file=sys.stderr)
        return 2
    if not args.truth.exists():
        print(f"[FAIL] truth not found: {args.truth}", file=sys.stderr)
        return 2

    try:
        summary, findings = run_audit(args.tex, args.truth)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[FAIL] truth schema error: {e}", file=sys.stderr)
        return 2

    audit_id = f"reverse-verify-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if args.out is not None:
        out_json = args.out
    else:
        out_dir = Path.cwd() / "audit"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir / f"reverse_verify_{datetime.now().strftime('%Y%m%d')}.json"

    out_json.parent.mkdir(parents=True, exist_ok=True)
    json_obj = {
        "audit_id": audit_id,
        "tex": str(args.tex),
        "truth": str(args.truth),
        "lang": args.lang,
        "summary": summary,
        "findings": findings,
    }
    out_json.write_text(json.dumps(json_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[报告] json -> {out_json}")

    print(f"[reverse_verify] tex: {args.tex}")
    print(f"[reverse_verify] truth: {args.truth}")
    print(f"[size] items={summary['total']} hit={summary['hit']} miss={summary['miss']}")
    print()

    error_count = sum(1 for f in findings if f["severity"] == "ERROR")
    warn_count = sum(1 for f in findings if f["severity"] == "WARN")
    info_count = sum(1 for f in findings if f["severity"] == "INFO")

    for f in findings:
        sev = f["severity"]
        tag = {"ERROR": "FAIL", "WARN": "WARN", "INFO": "INFO"}[sev]
        section_label = f" (§{f['section']})" if f["section"] else ""
        print(f"[{tag}] {f['name']}{section_label} candidates: {f['candidates']}")

    print()
    if summary["miss"] == 0:
        print(f"[PASS] 真值反推 {summary['total']}/{summary['total']} 命中")
    else:
        print(
            f"[FAIL] 真值反推 {summary['hit']}/{summary['total']} 命中, "
            f"{summary['miss']} miss "
            f"(ERROR={error_count} WARN={warn_count} INFO={info_count})"
        )

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
