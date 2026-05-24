"""
punct_audit.py —— 标点字符级核查（L-048 防回归）

针对中文 LaTeX 论文的 paper.tex 源做字符级标点审计，对齐 xelatex+ctex+宋体
渲染时的"肉眼盲区"问题（ASCII " 字形渲染都成关引号、半角逗号在中文段
应全角化但千分位数字应保留等）。

使用：
  python -m paper_agent.audit.rule.punct_audit --source <path>
  python -m paper_agent.audit.rule.punct_audit --source <path> --out findings.json
  python -m paper_agent.audit.rule.punct_audit --source <path> --lang zh
  python -m paper_agent.audit.rule.punct_audit --pdf --source <path-to-txt>

退出码 0 = 全部通过；1 = 有违规；2 = 文件不存在。

9 项检查（P1-P7 中文段标点字符级，P8-P9 LaTeX 通用语法级；
中文段 = `[一-鿿]` 字符前后 1 字符窗口）：

  P1 ASCII 直双引号 " (U+0022) 残留：必 0
  P2 日文括弧 「 (U+300C) / 」 (U+300D) 残留：必 0（中文应用 "" U+201C/D）
  P3 中文规范引号 " (U+201C) / " (U+201D) 配对：等量
  P4 ASCII 单引号 ' (U+0027) 在中文段：必 0（英文缩写 's 等例外）
  P5 中文段半角逗号 , (U+002C)：必 0（千分位数字 \\d,\\d{3} 白名单豁免）
  P6 中文段半角分号 ; (U+003B)：必 0
  P7 中文段半角冒号 : (U+003A)：必 0（URL / \\label{xxx:yyy} / 时间戳例外）
  P8 数学环境闭合 $...$ / $$...$$ / \\(...\\) / \\[...\\]：开闭数量平衡
  P9 悬空 \\ref / \\eqref / \\autoref / \\pageref / \\cref / \\Cref：key 必在 \\label{} 集

P10 悬空 \\cite{} 由 bib_audit.py dangling_cite 覆盖（跨 .tex/.bib），不在本工具职责内。

通用化设计（无学科 hardcode）：
  - P1-P7 中文规则归 rules-zh 范畴（U+FF00 段假设中文段）；规则字符从
    paper_agent.audit.rules.load_rules(lang) 读取，不 hardcode
  - P8-P9 LaTeX 语法层，语言无关
  - 测试 fixtures（tests/fixtures/with_unclosed_math.tex / with_dangling_ref.tex）
    至少 1 个非失语症 LaTeX 输入

补充诊断（不影响 PASS/FAIL，仅告知）：
  D1 全角空格 U+3000 在中文段：可能是误粘
  D2 不间断空格 U+00A0：可能是误粘
  D3 横线变体（— / – / ─ / -）混用：建议统一为 \\textemdash 或 ——
"""
import json
import re
import sys
import argparse
from pathlib import Path

from paper_agent.audit.rules import load_rules
from paper_agent._util import reconfigure_utf8

CN_CHAR = r"[一-鿿]"


# ----- helpers -----

def line_of(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def snippet_of(text: str, start: int, end: int, ctx: int = 15) -> str:
    return text[max(0, start - ctx):end + ctx].replace("\n", " ")


def scan(text: str, pat: str, name: str, flags: int = 0):
    matches = list(re.finditer(pat, text, flags))
    return matches


# ----- P8 / P9 LaTeX-syntax-level checks -----

LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
REF_RE = re.compile(
    r"\\(?:ref|eqref|autoref|pageref|cref|Cref|nameref|labelref)\*?\s*\{([^}]+)\}"
)


def find_math_tokens(text):
    """Walk text char-by-char, return list of (token_type, line_no).
    token_type in {'$', '\\(', '\\)', '\\[', '\\]'}.

    Honors LaTeX escape rules:
      - \\$  → literal dollar, skip both chars
      - \\\\ → newline command, skip both chars
      - \\( \\) \\[ \\] → math open/close, emit token
      - other \\X → consume the \\, leave X for next iteration
    """
    tokens = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
            continue
        if c == '\\' and i + 1 < n:
            nxt = text[i + 1]
            if nxt in ('$', '\\'):
                i += 2
                continue
            if nxt == '(':
                tokens.append(('\\(', line))
                i += 2
                continue
            if nxt == ')':
                tokens.append(('\\)', line))
                i += 2
                continue
            if nxt == '[':
                tokens.append(('\\[', line))
                i += 2
                continue
            if nxt == ']':
                tokens.append(('\\]', line))
                i += 2
                continue
            i += 1
            continue
        if c == '$':
            tokens.append(('$', line))
            i += 1
            continue
        i += 1
    return tokens


def check_math_envir(body):
    """P8: math environment balance (return list of finding dicts; empty = OK)."""
    tokens = find_math_tokens(body)
    findings = []
    dollar_lines = [ln for t, ln in tokens if t == '$']
    if len(dollar_lines) % 2 == 1:
        findings.append({
            "type": "unclosed_math_dollar",
            "count": len(dollar_lines),
            "last_line": dollar_lines[-1],
        })
    paren_open = sum(1 for t, _ in tokens if t == '\\(')
    paren_close = sum(1 for t, _ in tokens if t == '\\)')
    if paren_open != paren_close:
        findings.append({
            "type": "unclosed_math_paren",
            "open": paren_open,
            "close": paren_close,
        })
    brack_open = sum(1 for t, _ in tokens if t == '\\[')
    brack_close = sum(1 for t, _ in tokens if t == '\\]')
    if brack_open != brack_close:
        findings.append({
            "type": "unclosed_math_bracket",
            "open": brack_open,
            "close": brack_close,
        })
    return findings


def check_dangling_refs(body):
    """P9: dangling \\ref-family (return list of finding dicts; empty = OK)."""
    labels = set(LABEL_RE.findall(body))
    findings = []
    seen = set()
    for m in REF_RE.finditer(body):
        for key in m.group(1).split(','):
            key = key.strip()
            if not key or key in labels or key in seen:
                continue
            seen.add(key)
            line_no = body[: m.start()].count("\n") + 1
            findings.append({"type": "dangling_ref", "key": key, "line": line_no})
    return findings


def main():
    reconfigure_utf8()
    ap = argparse.ArgumentParser(
        description="punct_audit: 标点字符级核查 P1-P9"
    )
    ap.add_argument("--source", type=Path, default=None,
                    help="待扫描 .tex 或 .txt 路径（必须显式传入）")
    ap.add_argument("--pdf", action="store_true",
                    help="提示：若传入的 --source 是 pdftotext 反推 .txt，此 flag 仅供记录，无额外逻辑")
    ap.add_argument("--lang", default="zh", choices=["zh", "en", "ja"],
                    help="规则集语言 (en/ja 0.2.0+ placeholder)")
    ap.add_argument("--out", type=Path, default=None,
                    help="将 findings 以 JSON 格式写到指定路径（缺省仅 stdout）")
    args = ap.parse_args()

    if args.source is None:
        ap.error("--source PATH 是必填参数；不再默认推断 PROJECT_ROOT 路径。")

    src = args.source
    if not src.exists():
        print(f"[ERROR] 源文件不存在: {src}")
        sys.exit(2)

    # Load lang-pluggable P1-P7 character constants
    rules = load_rules(args.lang)
    pp = rules.get("punct_patterns", {})

    # Build P1-P7 patterns from rules; fall back to hardcoded chars if lang has no punct_patterns
    # (en/ja 0.2.0+ placeholders return empty dict → skip P1-P7 checks)
    have_punct = bool(pp)

    if have_punct:
        # Extract individual chars from the rule values
        _p1_char = pp.get("P1_ascii_double_quote_in_cn", '"')      # ASCII "

        _p2_raw = pp.get("P2_japanese_corner_quote", "「」")
        if len(_p2_raw) != 2:
            raise ValueError(
                f"P2_japanese_corner_quote must be exactly 2 chars (open+close), got {_p2_raw!r}"
            )
        _p2_open, _p2_close = _p2_raw[0], _p2_raw[1]

        _p3_raw = pp.get("P3_cn_curly_quote_pair", "“”")
        if len(_p3_raw) != 2:
            raise ValueError(
                f"P3_cn_curly_quote_pair must be exactly 2 chars (open+close), got {_p3_raw!r}"
            )
        _p3_ldq, _p3_rdq = _p3_raw[0], _p3_raw[1]
        _p4_char  = pp.get("P4_ascii_single_quote_in_cn", "'")     # ASCII '
        _p5_char  = pp.get("P5_halfwidth_comma_in_cn", ",")        # ,
        _p6_char  = pp.get("P6_halfwidth_semicolon_in_cn", ";")    # ;
        _p7_char  = pp.get("P7_halfwidth_colon_in_cn", ":")        # :

        # Build regex patterns (mirrors the original hardcoded patterns)
        P1_ASCII_DQUOTE = r'(?<!\\)"'
        P2_KAGI_OPEN    = re.escape(_p2_open)
        P2_KAGI_CLOSE   = re.escape(_p2_close)
        LDQ = _p3_ldq
        RDQ = _p3_rdq

        P4_ASCII_SQUOTE = (
            r"(?:" + CN_CHAR + r"\s*" + re.escape(_p4_char)
            + r"|" + re.escape(_p4_char) + r"\s*" + CN_CHAR + r")"
        )
        P5_HALF_COMMA = (
            r"(?:" + CN_CHAR + r"\s*" + re.escape(_p5_char)
            + r"(?!\d{3}(?:\D|$))"
            + r"|(?<!\d)\s*" + re.escape(_p5_char) + r"\s*" + CN_CHAR + r")"
        )
        P6_HALF_SEMI = (
            r"(?:" + CN_CHAR + r"\s*" + re.escape(_p6_char)
            + r"|" + re.escape(_p6_char) + r"\s*" + CN_CHAR + r")"
        )
        P7_HALF_COLON = (
            r"(?:" + CN_CHAR + r"\s*" + re.escape(_p7_char)
            + r"(?![A-Za-z0-9/])"
            + r"|(?<![A-Za-z0-9/])\s*" + re.escape(_p7_char) + r"\s*" + CN_CHAR + r")"
        )

    text = src.read_text(encoding="utf-8")

    if src.suffix == ".tex":
        body = "\n".join(
            re.sub(r"(?<!\\)%.*$", "", line)
            for line in text.splitlines()
        )
    else:
        body = text

    print(f"[punct_audit] 源: {src}  lang={args.lang}")
    print(f"[size] {len(body)} chars")
    print()

    fail = 0
    all_findings: list[dict] = []

    if have_punct:
        # P1 ASCII "
        n_dq = body.count(_p1_char)
        if n_dq > 0:
            print(f"[FAIL] P1 ASCII \" 残留: {n_dq} 处")
            for m in re.finditer(r'"', body):
                print(f"    L{line_of(body, m.start())}: ...{snippet_of(body, m.start(), m.end())}...")
                break
            fail += 1
            all_findings.append({"check": "P1", "count": n_dq})
        else:
            print("[ OK ] P1 ASCII \" 残留 0")

        # P2 「」
        n_kg_open  = body.count(_p2_open)
        n_kg_close = body.count(_p2_close)
        if n_kg_open or n_kg_close:
            print(f"[FAIL] P2 「 残留: {n_kg_open} / 」 残留: {n_kg_close}")
            fail += 1
            all_findings.append({"check": "P2", "open": n_kg_open, "close": n_kg_close})
        else:
            print("[ OK ] P2 「」 残留 0")

        # P3 "" 配对
        n_ldq = body.count(LDQ)
        n_rdq = body.count(RDQ)
        if n_ldq != n_rdq:
            print(f"[FAIL] P3 “ / ” 不平衡: 开 {n_ldq} / 关 {n_rdq}")
            fail += 1
            all_findings.append({"check": "P3", "open": n_ldq, "close": n_rdq})
        else:
            print(f'[ OK ] P3 “ / ” 平衡（各 {n_ldq} 处）')

        # P4 ASCII '（中文段）
        p4_matches = scan(body, P4_ASCII_SQUOTE, "P4")
        if p4_matches:
            print(f"[FAIL] P4 ASCII ' 在中文段: {len(p4_matches)} 处")
            for m in p4_matches[:3]:
                print(f"    L{line_of(body, m.start())}: ...{snippet_of(body, m.start(), m.end())}...")
            fail += 1
            all_findings.append({"check": "P4", "count": len(p4_matches)})
        else:
            print("[ OK ] P4 ASCII ' 在中文段 0")

        # P5 半角逗号（中文段，排除千分位）
        p5_matches = scan(body, P5_HALF_COMMA, "P5")
        if p5_matches:
            print(f"[FAIL] P5 中文段半角逗号: {len(p5_matches)} 处")
            for m in p5_matches[:5]:
                print(f"    L{line_of(body, m.start())}: ...{snippet_of(body, m.start(), m.end())}...")
            fail += 1
            # Build suggested_fix: take the first violating line and replace halfwidth comma with fullwidth
            _first_m = p5_matches[0]
            _first_ln = line_of(body, _first_m.start()) - 1
            _lines = body.splitlines()
            _bad_line = _lines[_first_ln] if _first_ln < len(_lines) else ""
            _fixed_line = re.sub(r"(?<!\d),(?!\d{3}(?:\D|$))", "，", _bad_line)
            _suggested = _fixed_line if _fixed_line != _bad_line else None
            all_findings.append({"check": "P5", "count": len(p5_matches),
                                 "line": _first_ln + 1, "suggested_fix": _suggested})
        else:
            print("[ OK ] P5 中文段半角逗号 0（千分位已豁免）")

        # P6 半角分号（中文段）
        p6_matches = scan(body, P6_HALF_SEMI, "P6")
        if p6_matches:
            print(f"[FAIL] P6 中文段半角分号: {len(p6_matches)} 处")
            for m in p6_matches[:3]:
                print(f"    L{line_of(body, m.start())}: ...{snippet_of(body, m.start(), m.end())}...")
            fail += 1
            all_findings.append({"check": "P6", "count": len(p6_matches)})
        else:
            print("[ OK ] P6 中文段半角分号 0")

        # P7 半角冒号（中文段，排除 URL/label）
        p7_matches = scan(body, P7_HALF_COLON, "P7")
        if p7_matches:
            print(f"[FAIL] P7 中文段半角冒号: {len(p7_matches)} 处")
            for m in p7_matches[:3]:
                print(f"    L{line_of(body, m.start())}: ...{snippet_of(body, m.start(), m.end())}...")
            fail += 1
            all_findings.append({"check": "P7", "count": len(p7_matches)})
        else:
            print("[ OK ] P7 中文段半角冒号 0（URL/label 已豁免）")

    else:
        print(f"[ -- ] P1-P7 跳过（lang={args.lang!r} 无 punct_patterns 规则集，0.2.0+ 占位）")

    print()

    # P8 数学环境闭合 (lang-agnostic)
    p8 = check_math_envir(body)
    if p8:
        print(f"[FAIL] P8 数学环境未闭合: {len(p8)} 项")
        for f in p8:
            t = f["type"]
            if t == "unclosed_math_dollar":
                print(f"    $ 总数 {f['count']}（奇数），最末 $ 在 L{f['last_line']}")
            elif t == "unclosed_math_paren":
                print(f"    \\( ... \\) 不平衡: 开 {f['open']} / 关 {f['close']}")
            elif t == "unclosed_math_bracket":
                print(f"    \\[ ... \\] 不平衡: 开 {f['open']} / 关 {f['close']}")
        fail += 1
        all_findings.extend([{"check": "P8", **f} for f in p8])
    else:
        print("[ OK ] P8 数学环境 $/\\(/\\[ 全闭合")

    # P9 悬空 \ref / \eqref / \autoref / \pageref / \cref / \Cref / \nameref / \labelref
    p9 = check_dangling_refs(body)
    if p9:
        print(f"[FAIL] P9 悬空 \\ref-类: {len(p9)} 处")
        for f in p9[:5]:
            print(f"    L{f['line']}: \\ref{{{f['key']}}}")
        fail += 1
        all_findings.extend([{"check": "P9", **f} for f in p9])
    else:
        print("[ OK ] P9 悬空 \\ref-类 0")

    print()

    # 诊断 D1 / D2 （非 fail，只告知）
    n_fws  = body.count("　")   # 全角空格
    n_nbsp = body.count(" ")   # 不间断空格
    if n_fws:
        print(f"[INFO] D1 全角空格 U+3000: {n_fws} 处（可能是误粘，检查是否应为半角空格）")
    if n_nbsp:
        print(f"[INFO] D2 不间断空格 U+00A0: {n_nbsp} 处（可能是误粘）")

    print()

    # --out JSON output
    if args.out is not None:
        out_data = {
            "source": str(src),
            "lang": args.lang,
            "fail_count": fail,
            "findings": all_findings,
        }
        args.out.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[punct_audit] findings 已写入: {args.out}")

    if fail == 0:
        print("[PASS] 标点字符级核查全部通过")
        sys.exit(0)
    else:
        print(f"[FAIL TOTAL] {fail} 项需修订")
        sys.exit(1)


if __name__ == "__main__":
    main()
