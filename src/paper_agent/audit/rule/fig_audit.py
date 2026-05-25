"""
fig_audit.py —— 图（figure）一致性审计（spec §D.2 fig_audit / 0.1.1 路线图 M-B.1）

针对 LaTeX 论文项目，扫 paper.tex 内所有 \\begin{figure}...\\end{figure} /
\\begin{figure*}...\\end{figure*} 环境，做三项检查：

  1. label_duplicate         ERROR  同 \\label{fig:X} 在 figure 环境内出现 ≥ 2 次
  2. caption_too_short       WARN   \\caption 字符数 < 20（中文 / 英文都按 char 数）
  3. orphan_figure           WARN   figure 内的 label 没有任何 \\ref/\\autoref/\\cref/
                                     \\Cref/\\Vref 在正文里反向引用

可选 post-flight：chktex（外部工具）—— 若 `--use-chktex` 且 chktex 在 PATH，
合并其 LaTeX 静态检查 warning 为 INFO 级别 finding；不在 PATH 则 silently skip。

使用：
  python -m paper_agent.audit.rule.fig_audit --tex <path> --out <path.json>
  python -m paper_agent.audit.rule.fig_audit --tex <path> --use-chktex --out <path.json>

退出码：0 全部通过 / 1 有 ERROR-级 finding / 2 tex 文件不存在

通用化（spec §A.3 第五原则）：
  - 路径 CLI 参数化（--tex 必填）
  - rule 不 hardcode 学科特异 label naming（fig:X 是 LaTeX 通用约定，非学科特异）
  - 输出 schema 字段名中性（finding / severity / rule / label / line）
  - 学科特异规则归 projects/<name>/rules/

L-033 合规：只读 paper.tex，只写 audit 报告（.json）；不动 paper.tex 任何字节。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from paper_agent._util import reconfigure_utf8


# ---------------------------------------------------------------------------
# Regex 集合
# ---------------------------------------------------------------------------

# 行级 %-注释剥除（保留行号、\% 转义保留），与 reverse_verify / bib_audit 等价
COMMENT_RE = re.compile(r"(?<!\\)%.*$")

# \begin{figure} ... \end{figure}  /  \begin{figure*} ... \end{figure*}
FIGURE_ENV_RE = re.compile(
    r"\\begin\{(figure\*?)\}(.*?)\\end\{\1\}",
    flags=re.DOTALL,
)

# \label{KEY}  (KEY 不含 } 与空白)
LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")

# \ref / \autoref / \cref / \Cref / \Vref / \pageref / \nameref
REF_CMD_RE = re.compile(
    r"\\(?:ref|autoref|cref|Cref|Vref|pageref|nameref)\s*\{([^}]+)\}"
)

# \caption[short]{LONG}  —— LONG 用 brace-balanced 抓
CAPTION_HEAD_RE = re.compile(r"\\caption(?:\[[^\]]*\])?\s*\{")

CAPTION_MIN_CHARS = 20


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def strip_tex_comments(text: str) -> str:
    """剥除 LaTeX 行级 %-注释，保留行号。\\% 字面转义保留。"""
    return "\n".join(COMMENT_RE.sub("", line) for line in text.splitlines())


def _line_no(text: str, pos: int) -> int:
    """1-indexed line number for `pos` in `text`."""
    return text[:pos].count("\n") + 1


def find_figure_envs(text: str) -> list[dict]:
    """Return list of {env, body, start_line} for each figure[*] environment."""
    envs = []
    for m in FIGURE_ENV_RE.finditer(text):
        envs.append({
            "env": m.group(1),  # 'figure' or 'figure*'
            "body": m.group(2),
            "start_line": _line_no(text, m.start()),
        })
    return envs


def extract_labels(body: str) -> list[str]:
    """All \\label{KEY} in env body, in document order."""
    return [m.group(1).strip() for m in LABEL_RE.finditer(body)]


def extract_caption(body: str) -> str:
    """Extract \\caption[short]{LONG} balanced-brace LONG. '' if no \\caption."""
    m = CAPTION_HEAD_RE.search(body)
    if not m:
        return ""
    i = m.end()  # right after '{'
    depth = 1
    n = len(body)
    j = i
    while j < n and depth > 0:
        c = body[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        j += 1
    return body[i : j - 1] if depth == 0 else body[i:]


def find_ref_keys(text: str) -> set[str]:
    """All keys referenced by \\ref/\\autoref/\\cref/\\Cref/\\Vref/etc.

    \\cref{a,b,c} 支持多 key 拆分。
    """
    keys: set[str] = set()
    for m in REF_CMD_RE.finditer(text):
        for k in m.group(1).split(","):
            k = k.strip()
            if k:
                keys.add(k)
    return keys


# ---------------------------------------------------------------------------
# Audit core
# ---------------------------------------------------------------------------

def run_audit(tex_path: Path) -> tuple[dict, list[dict]]:
    """Returns (summary, findings)."""
    text_raw = tex_path.read_text(encoding="utf-8")
    text = strip_tex_comments(text_raw)

    envs = find_figure_envs(text)
    ref_keys = find_ref_keys(text)

    findings: list[dict] = []
    all_labels: list[tuple[str, int]] = []  # (label_key, source_line)

    for env in envs:
        body = env["body"]
        start_line = env["start_line"]
        labels = extract_labels(body)
        caption = extract_caption(body)

        # Rule 2: caption_too_short
        if len(caption) < CAPTION_MIN_CHARS:
            findings.append({
                "severity": "WARN",
                "rule": "caption_too_short",
                "type": "caption_too_short",
                "file": str(tex_path),
                "line": start_line,
                "col": None,
                "message": (
                    f"figure[{env['env']}] caption 长度 {len(caption)} < "
                    f"{CAPTION_MIN_CHARS} 字符: '{caption[:40]}'"
                ),
                "label": labels[0] if labels else "",
                "caption": caption,
                "caption_length": len(caption),
                "suggested_fix": None,
            })

        for lab in labels:
            all_labels.append((lab, start_line))

    # Rule 1: label_duplicate（在 figure 环境内）
    seen: dict[str, int] = {}
    duplicates_reported: set[str] = set()
    for lab, line in all_labels:
        if lab in seen and lab not in duplicates_reported:
            duplicates_reported.add(lab)
            findings.append({
                "severity": "ERROR",
                "rule": "label_duplicate",
                "type": "label_duplicate",
                "file": str(tex_path),
                "line": line,
                "col": None,
                "message": (
                    f"\\label{{{lab}}} 在 figure 环境内重复出现 "
                    f"(首见 L{seen[lab]}, 重复 L{line})"
                ),
                "label": lab,
                "suggested_fix": None,
            })
        else:
            seen.setdefault(lab, line)

    # Rule 3: orphan_figure（figure 内的 label 未被反向引用）
    for lab, line in all_labels:
        if lab not in ref_keys:
            findings.append({
                "severity": "WARN",
                "rule": "orphan_figure",
                "type": "orphan_figure",
                "file": str(tex_path),
                "line": line,
                "col": None,
                "message": (
                    f"\\label{{{lab}}} 在 figure 内但正文无 "
                    f"\\ref/\\autoref/\\cref 反向引用"
                ),
                "label": lab,
                "suggested_fix": None,
            })

    summary = {
        "figure_count": len(envs),
        "label_count": len(all_labels),
        "ref_count": len(ref_keys),
        "label_duplicate_count": sum(
            1 for f in findings if f["rule"] == "label_duplicate"
        ),
        "caption_too_short_count": sum(
            1 for f in findings if f["rule"] == "caption_too_short"
        ),
        "orphan_figure_count": sum(
            1 for f in findings if f["rule"] == "orphan_figure"
        ),
    }
    return summary, findings


# ---------------------------------------------------------------------------
# Optional chktex post-flight
# ---------------------------------------------------------------------------

def chktex_post_flight(tex_path: Path) -> list[dict]:
    """Run chktex if available; convert its warnings to INFO findings.

    chktex output is line-by-line; we just capture stderr+stdout and emit as
    one INFO finding per non-empty warning line. If chktex is not installed,
    return [] (silent skip).
    """
    if not shutil.which("chktex"):
        return []
    try:
        result = subprocess.run(
            ["chktex", "-q", str(tex_path)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return []
    out_lines = (result.stdout + "\n" + result.stderr).splitlines()
    findings: list[dict] = []
    for line in out_lines:
        line = line.strip()
        if not line:
            continue
        findings.append({
            "severity": "INFO",
            "rule": "chktex_warn",
            "type": "chktex_warn",
            "file": str(tex_path),
            "line": 0,
            "col": None,
            "message": line,
            "suggested_fix": None,
        })
    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    reconfigure_utf8()
    ap = argparse.ArgumentParser(
        prog="paper_agent.audit.rule.fig_audit",
        description="图（figure）一致性审计：label 唯一 + caption ≥ 20 + ref 反向覆盖",
    )
    ap.add_argument("--tex", type=Path, required=True, help="paper.tex 路径")
    ap.add_argument(
        "--use-chktex", action="store_true",
        help="若 chktex 在 PATH，合并其 LaTeX 静态检查 warning（INFO 级别）",
    )
    ap.add_argument(
        "--lang", default="zh", choices=["zh", "en", "ja"],
        help="语言标签（当前 informational only）",
    )
    ap.add_argument("--out", type=Path, default=None, help="JSON 输出路径")
    args = ap.parse_args()

    if not args.tex.exists():
        print(f"[FAIL] tex not found: {args.tex}", file=sys.stderr)
        return 2

    summary, findings = run_audit(args.tex)

    if args.use_chktex:
        findings.extend(chktex_post_flight(args.tex))

    audit_id = f"fig-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if args.out is not None:
        out_json = args.out
    else:
        out_dir = Path.cwd() / "audit"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir / f"fig_audit_{datetime.now().strftime('%Y%m%d')}.json"

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

    print(f"[fig_audit] tex: {args.tex}")
    print(
        f"[size] figures={summary['figure_count']} "
        f"labels={summary['label_count']} refs={summary['ref_count']}"
    )
    print()

    error_count = sum(1 for f in findings if f["severity"] == "ERROR")
    warn_count = sum(1 for f in findings if f["severity"] == "WARN")
    info_count = sum(1 for f in findings if f["severity"] == "INFO")

    for f in findings[:20]:  # 限输出前 20
        sev = f["severity"]
        tag = {"ERROR": "FAIL", "WARN": "WARN", "INFO": "INFO"}[sev]
        line_label = f" L{f['line']}" if f.get("line") else ""
        print(f"[{tag}]{line_label} {f['rule']}: {f['message']}")

    print()
    if error_count == 0 and warn_count == 0 and info_count == 0:
        print("[PASS] fig_audit 全部通过")
    else:
        print(
            f"[fig_audit] ERROR={error_count} WARN={warn_count} INFO={info_count} "
            f"(figures={summary['figure_count']})"
        )

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
