"""
sample_audit.py —— 抽段人工复核 prompt（spec §D.2 sample_audit / 0.1.1 M-B.3）

随机抽 N 段 paper.tex 正文 paragraph，为每段生成一份"人工复核 prompt"模板，
作为 INFO-级 finding 输出。**永不阻断** compile 退出码（rc 恒为 0）。

设计动机：
  spec §D.2 的 sample_audit 设计目标是"在 LLM 评分之外，每次 audit 都强制人
  类抽查 N 段，防止全程 LLM-only 形成审计盲区"。本 rule 不调任何 LLM，只
  生成 paper-agnostic 的人工复核 prompt 模板，由人类 reviewer 完成实际判断。

使用：
  python -m paper_agent.audit.rule.sample_audit --tex <path> --n 3 --seed 42 --out <path.json>

参数：
  --n     抽段数，默认 3
  --seed  随机种子，默认 42（确保 audit 可重现）

退出码：始终 0（INFO 不阻断；sample_audit 是诊断辅助，不是失败判据）

paragraph 定义（spec §A.3 通用化原则）：
  - 空行分隔的非空文本块
  - 跳过 \\section/\\subsection/\\subsubsection 标题行
  - 跳过 LaTeX 环境（figure / table / equation / align / itemize / enumerate /
    verbatim / lstlisting / minted）内段落
  - 跳过 < MIN_PARAGRAPH_CHARS 字符的过短段
  - LaTeX %-注释剥除后再分段

通用化（spec §A.3 第五原则）：
  - 路径 CLI 参数化（--tex 必填）
  - prompt 模板不 hardcode 学科特异术语（无 BCC / ANOVA / 失语症 等）
  - 输出 schema 中性（finding / severity / rule / paragraph_text / line）

L-033 合规：只读 paper.tex，只写 audit 报告（.json）；不动 paper.tex 任何字节。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

from paper_agent._util import reconfigure_utf8


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_PARAGRAPH_CHARS = 30  # 短于此的段不进入抽样池（既能过滤章节标题，又接受短中文段）

# 跳过的 LaTeX 环境名（在这些环境内的内容不参与 paragraph 抽样）
SKIPPED_ENVS = {
    "figure", "figure*", "table", "table*",
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "itemize", "enumerate", "description",
    "verbatim", "lstlisting", "minted",
    "tikzpicture", "tabular",
}

# 段落首字符为这些 LaTeX 命令的认为是结构性标题/命令行，跳过
STRUCTURAL_HEADS = (
    "\\section", "\\subsection", "\\subsubsection",
    "\\paragraph", "\\chapter", "\\part",
    "\\title", "\\author", "\\date",
    "\\maketitle", "\\tableofcontents",
)

COMMENT_RE = re.compile(r"(?<!\\)%.*$")

# \begin{<env>} ... \end{<env>} （非贪婪、支持 *）
ENV_BLOCK_RE = re.compile(
    r"\\begin\{(\w+\*?)\}.*?\\end\{\1\}",
    flags=re.DOTALL,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _strip_comments(text: str) -> str:
    """剥行级 %-注释；保留行号。"""
    return "\n".join(COMMENT_RE.sub("", line) for line in text.splitlines())


def _mask_skipped_envs(text: str) -> str:
    """把被跳过的环境块整体替换成等行数的空白（保留行号）。

    使用迭代式 sub：先抓最外层 env，递归处理嵌套（罕见）通过多轮 sub 实现。
    """
    def _to_blanks(match: re.Match) -> str:
        env = match.group(1)
        block = match.group(0)
        if env not in SKIPPED_ENVS:
            return block  # 不是跳过列表的环境，保留
        # 保留行数：用 \n 占位
        n_newlines = block.count("\n")
        return "\n" * n_newlines

    prev = None
    cur = text
    # 迭代到稳定（处理嵌套 env，例如 itemize 内含 figure）
    while prev != cur:
        prev = cur
        cur = ENV_BLOCK_RE.sub(_to_blanks, cur)
    return cur


def extract_paragraphs(text: str) -> list[dict]:
    """从 LaTeX 源中提取候选 paragraph。

    Returns list of {text, line} sorted by document position.
      - text: paragraph 内容（已剥注释、已 strip 头尾空白）
      - line: 1-indexed 起始行号
    """
    body = _strip_comments(text)
    body = _mask_skipped_envs(body)

    paragraphs: list[dict] = []
    cur_lines: list[str] = []
    cur_start_line = 1
    line_no = 0

    def _flush(start: int, lines: list[str]):
        joined = "\n".join(lines).strip()
        if not joined:
            return
        # 结构性命令行（章节标题等）跳过
        if joined.startswith(STRUCTURAL_HEADS):
            return
        # 过短跳过
        if len(joined) < MIN_PARAGRAPH_CHARS:
            return
        paragraphs.append({"text": joined, "line": start})

    for line_no, raw in enumerate(body.splitlines(), start=1):
        if raw.strip() == "":
            _flush(cur_start_line, cur_lines)
            cur_lines = []
            cur_start_line = line_no + 1
        else:
            if not cur_lines:
                cur_start_line = line_no
            cur_lines.append(raw)

    _flush(cur_start_line, cur_lines)
    return paragraphs


def make_review_prompt(idx: int, paragraph_text: str, line_no: int) -> str:
    """生成 paper-agnostic 人工复核 prompt 模板。

    不 hardcode 学科特异术语；适用任何语言任何论文。
    """
    snippet = paragraph_text[:200] + ("..." if len(paragraph_text) > 200 else "")
    return (
        f"请审阅第 {idx} 段（paper.tex L{line_no}）是否满足以下三项:\n"
        f"  1. 事实准确 — 出现的数字 / 引用 / 论断都能在已发表来源中查证;\n"
        f"  2. 语言流畅 — 无 AI 套话、无标点错乱、无中英混排或低级语法错;\n"
        f"  3. 上下文连贯 — 与前后段逻辑一致, 论证链条无跳跃。\n"
        f"段落原文:\n{snippet}"
    )


# ---------------------------------------------------------------------------
# Audit core
# ---------------------------------------------------------------------------

def run_audit(
    tex_path: Path,
    n: int = 3,
    seed: int = 42,
) -> tuple[dict, list[dict]]:
    """抽 n 段生成人工复核 INFO finding。"""
    text = tex_path.read_text(encoding="utf-8")
    paragraphs = extract_paragraphs(text)

    rng = random.Random(seed)
    pool = list(paragraphs)
    sample_n = min(n, len(pool))
    if sample_n > 0:
        sampled = rng.sample(pool, sample_n)
        # 按原文位置排序（更好的可读性）
        sampled.sort(key=lambda p: p["line"])
    else:
        sampled = []

    findings: list[dict] = []
    for i, p in enumerate(sampled, start=1):
        findings.append({
            "severity": "INFO",
            "rule": "sample_review",
            "type": "sample_review",
            "file": str(tex_path),
            "line": p["line"],
            "col": None,
            "message": make_review_prompt(i, p["text"], p["line"]),
            "paragraph_text": p["text"],
            "paragraph_index": i,
            "suggested_fix": None,
        })

    summary = {
        "paragraph_pool": len(pool),
        "sampled": sample_n,
        "n_requested": n,
        "seed": seed,
    }
    return summary, findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    reconfigure_utf8()
    ap = argparse.ArgumentParser(
        prog="paper_agent.audit.rule.sample_audit",
        description="抽 N 段生成人工复核 prompt 模板（INFO，不阻断）",
    )
    ap.add_argument("--tex", type=Path, required=True, help="paper.tex 路径")
    ap.add_argument("--n", type=int, default=3, help="抽段数（默认 3）")
    ap.add_argument("--seed", type=int, default=42, help="随机种子（默认 42，可重现）")
    ap.add_argument(
        "--lang", default="zh", choices=["zh", "en", "ja"],
        help="语言标签（当前 informational only）",
    )
    ap.add_argument("--out", type=Path, default=None, help="JSON 输出路径")
    args = ap.parse_args()

    if not args.tex.exists():
        print(f"[FAIL] tex not found: {args.tex}", file=sys.stderr)
        return 2

    summary, findings = run_audit(args.tex, n=args.n, seed=args.seed)

    audit_id = f"sample-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if args.out is not None:
        out_json = args.out
    else:
        out_dir = Path.cwd() / "audit"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir / f"sample_audit_{datetime.now().strftime('%Y%m%d')}.json"

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

    print(f"[sample_audit] tex: {args.tex}")
    print(
        f"[size] paragraph_pool={summary['paragraph_pool']} "
        f"sampled={summary['sampled']} seed={summary['seed']}"
    )
    print()

    for f in findings:
        print(f"[INFO] L{f['line']} (paragraph #{f['paragraph_index']})")
        for line in f["message"].splitlines():
            print(f"  {line}")
        print()

    if summary["sampled"] == 0:
        print("[INFO] no eligible paragraphs sampled (pool empty)")
    else:
        print(f"[sample_audit] {summary['sampled']} 段人工复核 prompt 已生成")

    return 0  # 始终 0：sample_audit 是 INFO 级别，不阻断 compile


if __name__ == "__main__":
    sys.exit(main())
