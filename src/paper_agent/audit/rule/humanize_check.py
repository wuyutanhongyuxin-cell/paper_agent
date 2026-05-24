"""
humanize_check.py —— 8 项 LaTeX 源 selfcheck（R1-R7 字符级黑名单 + R8 数字反查）

基于 chinese-docx-humanize skill 的 24 规则中可机械化扫描的 7 项 +
新增 R8 数字真值正向核（paper.tex digit token → 反查 --data-source）。

使用：
  python -m paper_agent.audit.rule.humanize_check --source <path>
  python -m paper_agent.audit.rule.humanize_check --source <path> --data-source <p1>
  python -m paper_agent.audit.rule.humanize_check --source <path> --out findings.json

退出码 0 = 全部 OK；1 = R1-R7 有命中（R8 WARN 不阻断）；2 = 文件不存在。

8 项规则覆盖：
  R1 LLM 痕迹：agent / LLM / AI / 大模型 / 生成式 / chatgpt / claude / gemini / gpt-
  R2 AI 高频中文词：本文 / 本研究 / 至关重要 / 旨在 / 推动 / 综上所述 / 不仅...而且 / 核心要义 / 赋能 / 破局
  R3 AI 高频英文词：delve / pivotal / unlock / facilitate / leveraging / robust（非"鲁棒"语境）
  R4 emoji 与符号装饰：emoji 区块 / === / --- / 箭头 → ⇒ ← ⇐
  R5 半角括号含中文：(说话) / (N=100 受试者)（应改全角）— 纯英文/数字 (PsychoPy) (N=100) 保留半角
  R6 千分位被误全角化：1，818，649（应保留半角 1,818,649）
  R7 章节标号 + 中文：单行 "1.1 章节名" 模式（应用 \\section 等命令）
  R8 数字反查：扫 paper.tex 全部数字 token → 在 --data-source 指定的 .json/.csv/.tsv/.txt 中反查；
              未命中标 WARN（不阻断，仅 advisory）— 防"凭记忆写数字"（L-045）

R8 数字 token 类型（按优先级，避免重复抓）：
  thousands_separated  1,234 / 1,234,567 / 1,234.56
  p_value              p < 0.05 / p = 0.001 / p > 0.10
  percentage           12.3% / 50%
  ratio                1 : 2 / 0.5:1
  decimal              0.7287 / 3.14
  large_integer        4 位以上整数（自动排除 1900-2199 范围内的年份）

R8 匹配豁免：
  - paper.tex 用千分位 1,818,649；data source 整数 1818649 → 命中（去逗号匹配）
  - paper.tex 用 92.5%；data source float 92.5 / int 925/100 → 浮点近似命中
  - 年份 2024 / 1985 / 2030 → 自动排除（不参与反查，不报 WARN）

通用化设计（无学科 hardcode）：
  - 所有规则路径 CLI 参数化
  - 数字 token regex 不预设学科（千分位 / 百分比 / p 值 / 比率 / 整数全覆盖）
  - data source 加载支持 .json/.csv/.tsv/.txt 四种格式（递归收集 number values）

注：R5 用 (?<!\\}) 排除 LaTeX `\\textsubscript{10}(说明)` 等数学注解里的合法半角括号。
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

from paper_agent._util import reconfigure_utf8
from paper_agent.audit.rules import load_rules

# R4 and R5-R7 are lang-agnostic structural patterns; kept as module-level constants.
# R1, R2, R3 word/pattern data come from load_rules(lang) at runtime.

RULES_STATIC = {
    "R4_emoji与符号装饰": r"[✀-⟿\U0001f300-\U0001faff]|===+|---+(?!\s|$)|→|⇒|←|⇐",
    "R5_半角括号": r"(?<!\})\([^()]*[一-鿿]+[^()]*\)",
    "R6_千分位被全角化": r"\d，\d{3}",
    "R7_章节标号双角": r"^\s*\d+\.\d+\s+[一-鿿]",
}

# R8: number token patterns (priority order — earlier patterns claim spans first)
NUMBER_PATTERNS = [
    (r"\bp\s*[<>=]\s*0?\.\d+\b", "p_value"),
    (r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?", "thousands_separated"),
    (r"\b\d+(?:\.\d+)?\s*%", "percentage"),
    (r"\b\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\b", "ratio"),
    (r"\b\d+\.\d+\b", "decimal"),
    (r"\b\d{4,}\b", "large_integer"),
]

YEAR_RE = re.compile(r"^\d{4}$")


def build_rules(lang: str) -> dict:
    """Build full RULES dict: R1-R3 from load_rules(lang), R4-R7 from static."""
    rules_data = load_rules(lang)
    llm_pat = rules_data.get("humanize_llm_traces", "") or r"(?!x)x"
    zh_words = rules_data.get("humanize_ai_zh_words", [])
    en_words = rules_data.get("humanize_ai_en_words", [])

    # R2: reconstruct the regex from word list, preserving negative-lookahead for 本文/本研究
    r2_parts = []
    for w in zh_words:
        if w in ("本文", "本研究"):
            r2_parts.append(f"{re.escape(w)}(?![\\s]*[为，：])")
        elif w == "不仅...而且":
            r2_parts.append(r"不仅.{0,8}而且")
        else:
            r2_parts.append(re.escape(w))
    r2_pat = "|".join(r2_parts) if r2_parts else r"(?!x)x"  # no-match fallback

    # R3: reconstruct from en word list with \b word-boundary wrapping
    r3_parts = []
    for w in en_words:
        if w == "robust":
            r3_parts.append(r"\brobust\b(?! 性)")
        else:
            r3_parts.append(r"\b" + re.escape(w) + r"\b")
    r3_pat = "|".join(r3_parts) if r3_parts else r"(?!x)x"

    rules = {
        "R1_LLM痕迹": llm_pat,
        "R2_AI高频词": r2_pat,
        "R3_英文高频词": r3_pat,
    }
    rules.update(RULES_STATIC)
    return rules


def extract_numbers(text):
    """Extract number tokens with positions and categories.

    Priority resolution: a span claimed by an earlier pattern cannot be re-claimed.
    Auto-excludes 4-digit tokens in [1900, 2199] (typical year range).
    """
    claimed = []  # list of (start, end)

    def overlaps(s, e):
        for ss, ee in claimed:
            if s < ee and e > ss:
                return True
        return False

    matched = []
    for pat, cat in NUMBER_PATTERNS:
        for m in re.finditer(pat, text):
            if overlaps(m.start(), m.end()):
                continue
            token = m.group(0)
            if cat == "large_integer" and YEAR_RE.match(token):
                v = int(token)
                if 1900 <= v <= 2199:
                    continue
            claimed.append((m.start(), m.end()))
            line_no = text[: m.start()].count("\n") + 1
            matched.append({"token": token.strip(), "cat": cat, "line": line_no})
    return matched


def _collect_json_numbers(obj, tokens):
    """Recursively collect all number/string-like values from a JSON object."""
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_json_numbers(v, tokens)
    elif isinstance(obj, list):
        for v in obj:
            _collect_json_numbers(v, tokens)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        tokens.add(str(obj))
        if isinstance(obj, int) and abs(obj) >= 1000:
            tokens.add(f"{obj:,}")
    elif isinstance(obj, str):
        tokens.add(obj.strip())


def load_data_sources(paths):
    """Load all data sources, return set of stringified tokens (whitespace stripped)."""
    tokens = set()
    for path in paths:
        if not path.exists():
            print(f"[WARN] data source 不存在，跳过: {path}")
            continue
        suffix = path.suffix.lower()
        try:
            if suffix == ".json":
                with path.open(encoding="utf-8") as f:
                    obj = json.load(f)
                _collect_json_numbers(obj, tokens)
            elif suffix in (".csv", ".tsv"):
                delim = "\t" if suffix == ".tsv" else ","
                with path.open(encoding="utf-8", newline="") as f:
                    reader = csv.reader(f, delimiter=delim)
                    for row in reader:
                        for cell in row:
                            if cell:
                                tokens.add(cell.strip())
            else:
                content = path.read_text(encoding="utf-8")
                for tok in re.split(r"\s+", content):
                    if tok:
                        tokens.add(tok.strip())
        except Exception as e:
            print(f"[WARN] 解析 data source 失败 {path}: {e}")
    return tokens


def match_number(token, cat, source_tokens):
    """Try multiple variants; return True if any matches a source token."""
    variants = {token, token.strip()}
    no_comma = token.replace(",", "")
    variants.add(no_comma)
    no_percent = token.rstrip("%").rstrip()
    variants.add(no_percent)
    no_comma_no_percent = no_comma.rstrip("%").rstrip()
    variants.add(no_comma_no_percent)
    if cat == "p_value":
        m = re.search(r"\d+\.\d+", token)
        if m:
            variants.add(m.group(0))
    if cat == "ratio":
        # 1 : 2 / 0.5:1 等 → 两个分量都必须在 source 才算命中
        parts = [p.strip() for p in re.split(r"\s*:\s*", token) if p.strip()]
        if len(parts) >= 2:
            if all(p in source_tokens for p in parts):
                return True
            try:
                target_vals = [float(p) for p in parts]
                float_src = set()
                for st in source_tokens:
                    try:
                        float_src.add(float(st))
                    except ValueError:
                        continue
                if all(any(abs(t - sv) < 1e-9 for sv in float_src) for t in target_vals):
                    return True
            except ValueError:
                pass
    for v in variants:
        if v in source_tokens:
            return True
    # numeric approximate match
    try:
        candidates = []
        for v in variants:
            try:
                candidates.append(float(v))
            except ValueError:
                continue
        for st in source_tokens:
            try:
                sv = float(st)
            except ValueError:
                continue
            for c in candidates:
                if abs(c - sv) < 1e-9:
                    return True
                denom = max(abs(c), abs(sv), 1.0)
                if abs(c - sv) / denom < 1e-6:
                    return True
    except Exception:
        pass
    return False


def run_r8(body, data_sources):
    """Returns list of unmatched number findings."""
    source_tokens = load_data_sources(data_sources)
    paper_nums = extract_numbers(body)
    unmatched = []
    for n in paper_nums:
        if not match_number(n["token"], n["cat"], source_tokens):
            unmatched.append(n)
    return paper_nums, unmatched


def main():
    reconfigure_utf8()

    ap = argparse.ArgumentParser(description="LaTeX 源 humanize 8 项 selfcheck")
    ap.add_argument("--source", type=Path, default=None,
                    help="待扫描的 .tex 文件路径（必须）")
    ap.add_argument("--lang", default="zh", choices=["zh", "en", "ja"],
                    help="规则语言 (default: zh)")
    ap.add_argument(
        "--data-source", type=str, default="",
        help="R8 数字反查数据源路径，逗号分隔 .json/.csv/.tsv/.txt（默认空，跳过 R8）",
    )
    ap.add_argument("--out", type=Path, default=None,
                    help="将发现以 JSON 格式写入指定路径（可选）")
    args = ap.parse_args()

    if args.source is None:
        ap.error("--source is required")

    src = args.source
    if not src.exists():
        print(f"[ERROR] 源文件不存在: {src}")
        sys.exit(2)

    text = src.read_text(encoding="utf-8")
    body = "\n".join(
        re.sub(r"(?<!\\)%.*$", "", line)
        for line in text.splitlines()
    )

    print(f"[humanize_check] {src}")
    print(f"[size] {len(body)} chars (正文，已去注释)")
    print()

    RULES = build_rules(args.lang)

    findings = []
    total_hits = 0
    for name, pat in RULES.items():
        flags = re.MULTILINE if name == "R7_章节标号双角" else 0
        matches = list(re.finditer(pat, body, flags))
        if matches:
            print(f"[FAIL] {name}: {len(matches)} 处")
            for m in matches[:5]:
                line_no = body[: m.start()].count("\n") + 1
                snippet = body[max(0, m.start() - 15): m.end() + 15].replace("\n", " ")
                print(f"    L{line_no}: ...{snippet}...")
                findings.append({
                    "rule": name,
                    "line": line_no,
                    "token": m.group(0),
                    "snippet": snippet,
                })
            if len(matches) > 5:
                extra = matches[5:]
                print(f"    ... 另 {len(extra)} 处")
                for m in extra:
                    line_no = body[: m.start()].count("\n") + 1
                    snippet = body[max(0, m.start() - 15): m.end() + 15].replace("\n", " ")
                    findings.append({
                        "rule": name,
                        "line": line_no,
                        "token": m.group(0),
                        "snippet": snippet,
                    })
            total_hits += len(matches)
        else:
            print(f"[ OK ] {name}")

    # R8 数字反查（advisory，不计入 total_hits）
    data_sources = [Path(p.strip()) for p in args.data_source.split(",") if p.strip()]
    if data_sources:
        paper_nums, unmatched = run_r8(body, data_sources)
        if unmatched:
            print(f"[WARN] R8_数字未在数据源命中: {len(unmatched)} / {len(paper_nums)} 处")
            for n in unmatched[:10]:
                print(f"    L{n['line']} ({n['cat']}): {n['token']}")
                findings.append({
                    "rule": "R8_数字反查",
                    "line": n["line"],
                    "token": n["token"],
                    "cat": n["cat"],
                    "message": f"unmatched: {n['token']}",
                })
            if len(unmatched) > 10:
                extra_r8 = unmatched[10:]
                print(f"    ... 另 {len(extra_r8)} 处")
                for n in extra_r8:
                    findings.append({
                        "rule": "R8_数字反查",
                        "line": n["line"],
                        "token": n["token"],
                        "cat": n["cat"],
                        "message": f"unmatched: {n['token']}",
                    })
        else:
            print(f"[ OK ] R8_数字反查: 全部 {len(paper_nums)} 处数字在数据源中找到")
    else:
        print("[SKIP] R8_数字反查: 未指定 --data-source，跳过")

    # Write JSON output if requested
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        out_obj = {
            "source": str(src),
            "lang": args.lang,
            "findings": findings,
        }
        args.out.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[out] {args.out} ({len(findings)} findings)")

    print()
    if total_hits == 0:
        print("[PASS] R1-R7 全部 OK（R8 见上方 WARN/SKIP 状态）")
        sys.exit(0)
    else:
        print(f"[FAIL TOTAL] R1-R7 共 {total_hits} 处需修订")
        sys.exit(1)


if __name__ == "__main__":
    main()
