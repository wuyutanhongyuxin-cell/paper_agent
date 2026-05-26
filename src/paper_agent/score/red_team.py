"""score/red_team.py — paper-agent 0.1.1 红队反诘 prompt 池 (M-E.1).

实现 spec §D.4 红队反诘 contract：把 PaperOrchestra MIT red-team prompt 池中
7 个通用 failure mode 固化为 paper-agnostic 子模块。可选的 detector_regex
路径让 obvious 案例不依赖 LLM 即可命中；LLM-only modes 通过 evaluator hook
注入 (M-E.2 `ensemble.py` 或 M-F 真 LLM 调用)。

7 个 failure modes (spec §D.4 顺序锁死):

  1. factual_fabrication   — 凭空捏造数字 / 引用 / 实验结果
  2. methodology_handwave  — 含糊方法描述无法复现
  3. selective_reporting   — 只报正向结果，未报负面 / null result
  4. citation_inflation    — 自引 / 客套引用过度
  5. ethics_omission       — IRB / 知情同意 / 数据来源不透明
  6. stat_misuse           — p-hacking / 多重比较未校正 / 错误效应量
  7. scope_overclaim       — 结论超越数据支持范围 (含 T5 社工诱导词)

paper-agnostic 承诺：
  - prompt_template 全 generic, 不 hardcode 学科 / 语言 / paper 名
  - paper_id 完全来自 CLI / 调用方
  - L-033 read-only: 本模块只读 paper.tex, 永不写 paper.tex
  - 输出仅写 out/red_team_*.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .dimensions import EvidenceRef


# ---------------------------------------------------------------------------
# 7 failure modes (spec §D.4 顺序锁死)
# ---------------------------------------------------------------------------

DEFAULT_FAILURE_MODES: tuple[str, ...] = (
    "factual_fabrication",
    "methodology_handwave",
    "selective_reporting",
    "citation_inflation",
    "ethics_omission",
    "stat_misuse",
    "scope_overclaim",
)


# ---------------------------------------------------------------------------
# Safe-revision 白名单 regex
# ---------------------------------------------------------------------------

# 红队改写建议如能匹配此模式即可标记为 safe_revision=True，
# 表示 edit_gate Layer 3 可低风险应用 (语义保守、单一动作、范围明确).
#
# 形式：<action> <scope>: <content>
#   action ∈ {replace, delete, reword}
#   scope  ∈ {phrase, sentence, clause}
SAFE_REVISION_RE = re.compile(
    r"^\s*(?P<action>replace|delete|reword)"
    r"\s+(?P<scope>phrase|sentence|clause)"
    r"\s*:\s*(?P<content>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def is_safe_revision(suggestion: str) -> bool:
    """红队 revision 建议是否匹配 SAFE_REVISION_RE 白名单。

    白名单的目的：缩小 edit_gate Layer 3 应用 patch 时的语义风险。
    """
    if not suggestion:
        return False
    return SAFE_REVISION_RE.match(suggestion) is not None


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedTeamCheck:
    """单个 failure mode 的契约 (paper-agnostic).

    - prompt_template: LLM 红队 prompt (generic, 无学科 / 语言 hardcode)
    - detector_regex:  可选 fast-path 正则；None 表示 LLM-only mode
    """
    mode: str
    severity: str  # ERROR / WARN / INFO
    prompt_template: str
    detector_regex: re.Pattern[str] | None = None


@dataclass(frozen=True)
class RedTeamFinding:
    """单次红队命中。"""
    mode: str
    severity: str
    message: str
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    safe_revision: bool = False

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "severity": self.severity,
            "message": self.message,
            "evidence": [{"file": e.file, "line": e.line} for e in self.evidence],
            "safe_revision": self.safe_revision,
        }


# ---------------------------------------------------------------------------
# CHECKS registry (7 modes)
# ---------------------------------------------------------------------------

# scope_overclaim 的 fast-path：英文社工诱导词 + 中文同义
# 仅命中边界明确的 case，避免误伤数学 / 物理论文里 "obvious" 的合理用法
_SCOPE_OVERCLAIM_RE = re.compile(
    r"(?ix)"
    r"\b(?:obviously|trivially|undoubtedly|undeniably)\b"
    r"|"
    r"\bclearly\s+(?:demonstrates?|shows?|proves?)\b"
    r"|"
    r"\bof\s+course\b\s*[,，]?\s*(?:our|the\s+proposed)"
    r"|"
    r"显然.{0,8}(?:证明|表明|说明)"
    r"|"
    r"毫无疑问"
    r"|"
    r"显而易见.{0,8}(?:优于|超越|证明)",
)


CHECKS: tuple[RedTeamCheck, ...] = (
    RedTeamCheck(
        mode="factual_fabrication",
        severity="ERROR",
        prompt_template=(
            "Inspect the manuscript for fabricated facts: numbers, citations, "
            "experimental results, or quotes that do not appear in any cited "
            "source. For each suspicion, return file/line and a one-sentence "
            "challenge. Do not invent evidence; if uncertain, abstain."
        ),
        detector_regex=None,
    ),
    RedTeamCheck(
        mode="methodology_handwave",
        severity="WARN",
        prompt_template=(
            "Identify methodology descriptions too vague to reproduce: "
            "missing hyperparameters, undefined preprocessing, ambiguous "
            "metric definitions, or unstated random seeds. Cite the offending "
            "line and propose the minimum information needed."
        ),
        detector_regex=None,
    ),
    RedTeamCheck(
        mode="selective_reporting",
        severity="WARN",
        prompt_template=(
            "Look for selective reporting: positive results stated without "
            "matched negative / null controls, ablations missing for claimed "
            "components, or cherry-picked subsets. Cite location and propose "
            "the missing comparison."
        ),
        detector_regex=None,
    ),
    RedTeamCheck(
        mode="citation_inflation",
        severity="WARN",
        prompt_template=(
            "Audit the bibliography for citation inflation: excessive "
            "self-citation, courtesy citations to unrelated work, or citations "
            "used as decoration rather than evidence. Flag each suspicious "
            "entry with reason."
        ),
        detector_regex=None,
    ),
    RedTeamCheck(
        mode="ethics_omission",
        severity="ERROR",
        prompt_template=(
            "Check that ethics obligations are addressed where applicable: "
            "IRB / ethics-board approval, informed consent, data provenance, "
            "PII handling, dual-use considerations, conflict of interest. "
            "Flag missing or evasive statements."
        ),
        detector_regex=None,
    ),
    RedTeamCheck(
        mode="stat_misuse",
        severity="WARN",
        prompt_template=(
            "Detect statistical misuse: p-hacking signals (many ad-hoc tests, "
            "no correction for multiple comparisons), inappropriate effect "
            "size, wrong test for the design, missing assumption checks "
            "(normality, homoscedasticity), or confusing significance with "
            "effect size."
        ),
        detector_regex=None,
    ),
    RedTeamCheck(
        mode="scope_overclaim",
        severity="WARN",
        prompt_template=(
            "Identify conclusions that exceed the evidence base: "
            "social-engineering language ('obviously', 'clearly demonstrates', "
            "'trivially', '显然', '毫无疑问'), generalizations beyond the "
            "tested population / dataset / regime, or claims of causality "
            "without identification strategy."
        ),
        detector_regex=_SCOPE_OVERCLAIM_RE,
    ),
)

_CHECK_BY_MODE: dict[str, RedTeamCheck] = {c.mode: c for c in CHECKS}


# ---------------------------------------------------------------------------
# 核心入口
# ---------------------------------------------------------------------------


def run_red_team(
    tex_path: Path,
    *,
    modes: Iterable[str] | None = None,
    paper_id: str = "",
    evaluator: Callable[[str, str, str], list[RedTeamFinding]] | None = None,
) -> list[RedTeamFinding]:
    """对 paper.tex 跑红队检测。

    Args:
        tex_path: paper.tex 路径 (L-033 read-only — 本函数只读)
        modes: 要跑的 mode 集合；None = 全 7 个
        paper_id: 论文标识 (CLI 参数化，永不 hardcode)
        evaluator: 可选 LLM 调用 (mode, tex_text, paper_id) -> list[RedTeamFinding]
                   detector_regex=None 的 modes 仅在 evaluator 非 None 时执行

    Returns:
        list[RedTeamFinding]
    """
    if modes is None:
        target_modes: tuple[str, ...] = DEFAULT_FAILURE_MODES
    else:
        target_modes = tuple(modes)
        unknown = set(target_modes) - set(DEFAULT_FAILURE_MODES)
        if unknown:
            raise ValueError(
                f"unknown red-team modes: {sorted(unknown)}; "
                f"valid = {list(DEFAULT_FAILURE_MODES)}"
            )

    tex_text = tex_path.read_text(encoding="utf-8")
    findings: list[RedTeamFinding] = []

    for mode in target_modes:
        check = _CHECK_BY_MODE[mode]
        if check.detector_regex is not None:
            findings.extend(_apply_regex_detector(check, tex_text, tex_path))
        else:
            if evaluator is not None:
                findings.extend(evaluator(mode, tex_text, paper_id))
            # evaluator=None → 静默 skip LLM-only modes

    return findings


def _apply_regex_detector(
    check: RedTeamCheck,
    tex_text: str,
    tex_path: Path,
) -> list[RedTeamFinding]:
    """对带 detector_regex 的 mode 做行级扫描。"""
    assert check.detector_regex is not None
    out: list[RedTeamFinding] = []
    for lineno, line in enumerate(tex_text.splitlines(), start=1):
        # 跳过 LaTeX 注释行 (行首 %)
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        m = check.detector_regex.search(line)
        if not m:
            continue
        out.append(
            RedTeamFinding(
                mode=check.mode,
                severity=check.severity,
                message=f"{check.mode} pattern matched: {m.group(0)!r}",
                evidence=(EvidenceRef(file=tex_path.name, line=lineno),),
                safe_revision=False,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Module-level CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m paper_agent.score.red_team",
        description="Red-team failure-mode detector (M-E paper-agent 0.1.1).",
    )
    parser.add_argument("--tex", type=Path, required=True, help="Path to paper.tex")
    parser.add_argument(
        "--paper-id",
        type=str,
        default="",
        help="Paper identifier (CLI-injected, never hardcoded).",
    )
    parser.add_argument(
        "--modes",
        type=str,
        nargs="*",
        default=None,
        help=f"Subset of {list(DEFAULT_FAILURE_MODES)}; default = all.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output JSON path; defaults to stdout.",
    )
    args = parser.parse_args(argv)

    if not args.tex.exists():
        print(f"[FAIL] tex not found: {args.tex}", file=sys.stderr)
        return 2

    findings = run_red_team(
        args.tex,
        modes=args.modes,
        paper_id=args.paper_id,
        evaluator=None,
    )

    payload = {
        "paper_id": args.paper_id,
        "tex": str(args.tex),
        "findings": [f.to_dict() for f in findings],
        "mode_summary": {
            m: sum(1 for f in findings if f.mode == m)
            for m in DEFAULT_FAILURE_MODES
        },
    }
    blob = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob, encoding="utf-8")
        print(f"[red_team] -> {args.out}")
    else:
        print(blob)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
