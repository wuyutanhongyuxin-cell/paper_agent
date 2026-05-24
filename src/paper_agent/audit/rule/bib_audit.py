"""
bib_audit.py —— BibTeX 引用一致性审计

针对 LaTeX 论文项目，扫 paper.tex 所有 \\cite-类命令 key 与 references.bib 的
@<type>{key,...} entries 做双向 set diff；检测 TODO 占位 entries；可选必填字段检查。

使用：
  python -m paper_agent.audit.rule.bib_audit --tex <path> --bib <path>
  python -m paper_agent.audit.rule.bib_audit --tex <path> --bib <path> --required-fields author,title,year
  python -m paper_agent.audit.rule.bib_audit --tex <path> --bib <path> --todo-pattern '^TODO_'
  python -m paper_agent.audit.rule.bib_audit --tex <path> --bib <path> --out <path.json>
  python -m paper_agent.audit.rule.bib_audit --tex <path> --bib <path> --use-biber-tool
  python -m paper_agent.audit.rule.bib_audit --tex <path> --bib <path> --use-bibtool

退出码：0 全部通过 / 1 有 ERROR-级 finding / 2 文件不存在

五类 finding（严重度）：
  dangling_cite          ERROR  paper.tex 引用了 bib 中不存在的 key
  todo_placeholder       ERROR  bib 中有 active 占位 entries（key 匹配 --todo-pattern）
  unused_entry           WARN   bib 中有未被引用的 entries
  missing_field          WARN   bib entries 缺必填字段（若启用 --required-fields）
  commented_placeholder  INFO   bib 注释里有 `% @<type>{<key>` 形式的 TODO 占位
                                （biber 不会编入 PDF；不阻断退出码；提醒待补）

支持的 \\cite-类命令：
  \\cite{} \\citep{} \\citet{} \\citeauthor{} \\citeyear{}
  \\parencite{} \\textcite{} \\footcite{} \\autocite{} \\nocite{}
  含可选参数 [pre][post] 与逗号分隔多 key（\\cite{a,b,c}）

通用化设计（无学科 hardcode）：
  - 所有路径 CLI 参数化（--tex / --bib 均为必填）
  - 输出 schema 字段名中性（finding / severity / type / key / ...）
  - 测试 fixtures 至少 1 个非失语症 LaTeX pair（见 tests/fixtures/）
  - 引擎不识别学科特异规则；学科规则归 projects/<name>/rules/

L-033 合规：本工具只读 .tex / .bib，只写 audit 报告（.md / .json）；
不动 paper.tex / references.bib 任何字节。
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from paper_agent._util import reconfigure_utf8

CITE_CMD_RE = re.compile(
    r"\\(?:cite|citep|citet|citeauthor|citeyear|parencite|textcite|footcite|autocite|nocite)"
    r"\s*(?:\[[^\]]*\])?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
)

BIB_ENTRY_START_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s}]+)\s*,")

COMMENTED_ENTRY_RE = re.compile(
    r"^\s*%\s*@(\w+)\s*\{\s*([^,\s}]+)\s*,", re.MULTILINE
)


def strip_bib_comments_preserve_lines(text: str) -> str:
    """Blank out lines starting with '%' (BibTeX convention), keep line numbers.

    BibTeX strict spec has no '%' comments, but biber/biblatex tolerate them
    as 'junk before entry'. We strip them so parse_bib_entries does not
    confuse commented entries for active ones.
    """
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def find_commented_placeholders(text: str, todo_re):
    """Scan raw bib text for `% @<type>{<key>,` lines whose key matches todo_re."""
    results = []
    for m in COMMENTED_ENTRY_RE.finditer(text):
        key = m.group(2)
        if not todo_re.search(key):
            continue
        line_no = text[: m.start()].count("\n") + 1
        results.append({
            "severity": "INFO",
            "type": "commented_placeholder",
            "key": key,
            "bib_line": line_no,
            "bib_context": get_line_context(text, line_no),
        })
    return results


def parse_bib_entries(text: str):
    """Brace-balanced BibTeX parser.

    Returns list of {type, key, line, fields: {name -> value}}.
    Skips @string / @preamble / @comment.
    """
    entries = []
    i = 0
    n = len(text)
    while i < n:
        m = BIB_ENTRY_START_RE.search(text, i)
        if not m:
            break
        entry_type = m.group(1).lower()
        entry_key = m.group(2)
        line_no = text[: m.start()].count("\n") + 1
        body_start = m.end()
        depth = 1
        j = body_start
        while j < n and depth > 0:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        body = text[body_start : j - 1] if depth == 0 else text[body_start:]
        i = j
        if entry_type in {"string", "preamble", "comment"}:
            continue
        fields = parse_bib_fields(body)
        entries.append(
            {"type": entry_type, "key": entry_key, "line": line_no, "fields": fields}
        )
    return entries


def parse_bib_fields(body: str):
    """Parse `name = {value} | "value" | bare` fields, brace-balanced."""
    fields = {}
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " ,\t\r\n":
            i += 1
        if i >= n:
            break
        m = re.match(r"(\w+)\s*=\s*", body[i:])
        if not m:
            i += 1
            continue
        name = m.group(1).lower()
        i += m.end()
        if i >= n:
            break
        c = body[i]
        if c == "{":
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                j += 1
            value = body[i + 1 : j - 1] if depth == 0 else body[i + 1 : j]
            i = j
        elif c == '"':
            j = i + 1
            while j < n and body[j] != '"':
                if body[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                j += 1
            value = body[i + 1 : j]
            i = j + 1 if j < n else j
        else:
            m2 = re.match(r"(\S+)", body[i:])
            if m2:
                value = m2.group(1).rstrip(",")
                i += len(m2.group(1))
            else:
                value = body[i:].strip()
                i = n
        fields[name] = value.strip()
    return fields


def extract_cite_keys(tex_text: str):
    """Return list of (key, line_no), document-order, preserving duplicates."""
    results = []
    for m in CITE_CMD_RE.finditer(tex_text):
        line_no = tex_text[: m.start()].count("\n") + 1
        for key in m.group(1).split(","):
            key = key.strip()
            if key:
                results.append((key, line_no))
    return results


def strip_tex_comments(tex_text: str) -> str:
    return "\n".join(
        re.sub(r"(?<!\\)%.*$", "", line) for line in tex_text.splitlines()
    )


def get_line_context(text: str, line_no: int) -> str:
    lines = text.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def run_audit(tex_path, bib_path, required_fields, todo_pattern):
    """Returns (summary_dict, findings_list)."""
    tex_path = Path(tex_path)
    bib_path = Path(bib_path)
    if not tex_path.exists():
        print(f"[ERROR] tex 文件不存在: {tex_path}")
        sys.exit(2)
    if not bib_path.exists():
        print(f"[ERROR] bib 文件不存在: {bib_path}")
        sys.exit(2)

    tex_raw = tex_path.read_text(encoding="utf-8")
    tex_body = strip_tex_comments(tex_raw)
    bib_text_raw = bib_path.read_text(encoding="utf-8")
    bib_text_active = strip_bib_comments_preserve_lines(bib_text_raw)

    entries = parse_bib_entries(bib_text_active)
    bib_keys = {e["key"] for e in entries}

    cite_pairs = extract_cite_keys(tex_body)
    cited_keys = {k for k, _ in cite_pairs}

    findings = []
    todo_re = re.compile(todo_pattern)

    seen_dangling = set()
    for key, line_no in cite_pairs:
        if key in bib_keys:
            continue
        if key in seen_dangling:
            continue
        seen_dangling.add(key)
        findings.append({
            "severity": "ERROR",
            "type": "dangling_cite",
            "key": key,
            "tex_line": line_no,
            "tex_context": get_line_context(tex_body, line_no),
        })

    for entry in entries:
        if todo_re.search(entry["key"]):
            findings.append({
                "severity": "ERROR",
                "type": "todo_placeholder",
                "key": entry["key"],
                "bib_line": entry["line"],
                "bib_context": get_line_context(bib_text_raw, entry["line"]),
            })

    findings.extend(find_commented_placeholders(bib_text_raw, todo_re))

    for entry in entries:
        if todo_re.search(entry["key"]):
            continue
        if entry["key"] not in cited_keys:
            findings.append({
                "severity": "WARN",
                "type": "unused_entry",
                "key": entry["key"],
                "bib_line": entry["line"],
            })

    if required_fields:
        for entry in entries:
            if todo_re.search(entry["key"]):
                continue
            for fname in required_fields:
                if fname.lower() not in entry["fields"]:
                    findings.append({
                        "severity": "WARN",
                        "type": "missing_field",
                        "key": entry["key"],
                        "field": fname.lower(),
                        "bib_line": entry["line"],
                    })

    summary = {
        "cite_keys_in_tex": len(cited_keys),
        "entries_in_bib": len(entries),
        "dangling_cite_count": sum(1 for f in findings if f["type"] == "dangling_cite"),
        "todo_placeholder_count": sum(1 for f in findings if f["type"] == "todo_placeholder"),
        "unused_entry_count": sum(1 for f in findings if f["type"] == "unused_entry"),
        "missing_field_count": sum(1 for f in findings if f["type"] == "missing_field"),
        "commented_placeholder_count": sum(1 for f in findings if f["type"] == "commented_placeholder"),
    }
    return summary, findings


def render_md(audit_id, tex_path, bib_path, summary, findings) -> str:
    lines = [
        f"# bib_audit 报告 · {audit_id}",
        "",
        f"- **tex**: `{tex_path}`",
        f"- **bib**: `{bib_path}`",
        f"- **生成时间**: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- cite keys in tex: {summary['cite_keys_in_tex']}",
        f"- entries in bib: {summary['entries_in_bib']}",
        f"- dangling_cite: **{summary['dangling_cite_count']}** (ERROR)",
        f"- todo_placeholder: **{summary['todo_placeholder_count']}** (ERROR)",
        f"- unused_entry: **{summary['unused_entry_count']}** (WARN)",
        f"- missing_field: **{summary['missing_field_count']}** (WARN)",
        f"- commented_placeholder: **{summary['commented_placeholder_count']}** (INFO)",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.append("（无 finding，全部通过）")
    else:
        for f in findings:
            sev, t, k = f["severity"], f["type"], f["key"]
            if t == "dangling_cite":
                lines.append(f"- [{sev}] `{t}` `{k}` (tex L{f['tex_line']}): `{f['tex_context']}`")
            elif t == "todo_placeholder":
                lines.append(f"- [{sev}] `{t}` `{k}` (bib L{f['bib_line']}): `{f['bib_context']}`")
            elif t == "unused_entry":
                lines.append(f"- [{sev}] `{t}` `{k}` (bib L{f['bib_line']})")
            elif t == "missing_field":
                lines.append(f"- [{sev}] `{t}` `{k}` (bib L{f['bib_line']}) 缺字段 `{f['field']}`")
            elif t == "commented_placeholder":
                lines.append(f"- [{sev}] `{t}` `{k}` (bib L{f['bib_line']}, 注释中): `{f['bib_context']}`")
            else:
                lines.append(f"- [{sev}] `{t}` {f.get('key', '')} {f.get('message', '')}")
    lines.append("")
    return "\n".join(lines)


def biber_tool_validate(bib_path):
    """spec §D.2: biber --tool --validate-datamodel backend."""
    if not shutil.which("biber"):
        return [{"type": "biber_tool", "severity": "INFO", "key": "",
                 "message": "biber not in PATH; skipping --validate-datamodel"}]
    try:
        result = subprocess.run(
            ["biber", "--tool", "--validate-datamodel", str(bib_path)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        findings = []
        for line in (result.stdout + "\n" + result.stderr).splitlines():
            if line.startswith("ERROR"):
                findings.append({"type": "biber_tool.schema_error", "severity": "ERROR", "key": "",
                                 "file": str(bib_path), "line": 0, "message": line})
            elif line.startswith("WARN"):
                findings.append({"type": "biber_tool.schema_warn", "severity": "WARN", "key": "",
                                 "file": str(bib_path), "line": 0, "message": line})
        return findings
    except subprocess.TimeoutExpired:
        return [{"type": "biber_tool", "severity": "WARN", "key": "",
                 "message": "biber timeout 60s"}]
    except (FileNotFoundError, OSError):
        return [{"type": "biber_tool", "severity": "WARN", "key": "",
                 "message": "biber invocation failed (binary disappeared between which() and run())"}]


def bibtool_check(bib_path, todo_pattern="^TODO_"):
    if not shutil.which("bibtool"):
        return []
    rsc = f'select{{$key="{todo_pattern}"}}\n'
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".rsc", encoding="utf-8", delete=False
    ) as fh:
        fh.write(rsc)
        rsc_tmp = Path(fh.name)
    try:
        result = subprocess.run(
            ["bibtool", "-r", str(rsc_tmp), str(bib_path)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        findings = []
        for line in result.stdout.splitlines():
            if line.startswith("@"):
                key = line.split("{", 1)[1].split(",", 1)[0]
                findings.append({"type": "bibtool.todo_placeholder", "severity": "ERROR",
                                 "key": key, "file": str(bib_path), "line": 0,
                                 "message": f"key={key}"})
        return findings
    except (FileNotFoundError, OSError):
        return [{"type": "bibtool", "severity": "WARN", "key": "",
                 "message": "bibtool invocation failed"}]
    finally:
        rsc_tmp.unlink(missing_ok=True)


def main():
    reconfigure_utf8()

    ap = argparse.ArgumentParser(description="BibTeX 引用一致性审计")
    ap.add_argument("--tex", type=Path, required=False, default=None,
                    help="paper.tex 路径（必填）")
    ap.add_argument("--bib", type=Path, required=False, default=None,
                    help="references.bib 路径（必填）")
    ap.add_argument(
        "--required-fields", type=str, default="",
        help="逗号分隔的必填字段名，如 author,title,year,doi（默认空，不检查）",
    )
    ap.add_argument(
        "--todo-pattern", type=str, default=r"^TODO_",
        help="bib key 匹配此 regex 视为 TODO 占位（默认 '^TODO_'）",
    )
    ap.add_argument(
        "--out", type=str, default=None,
        help="JSON 输出路径（.json）。当提供时，仅写 JSON 到该路径。"
        "未提供时写 <prefix>.md + <prefix>.json 到 audit/ 目录。",
    )
    ap.add_argument(
        "--use-biber-tool", action="store_true",
        help="调用 biber --tool --validate-datamodel 并合并 findings（biber 不在 PATH 则跳过）",
    )
    ap.add_argument(
        "--use-bibtool", action="store_true",
        help="调用 bibtool 扫描 TODO 占位 key 并合并 findings（bibtool 不在 PATH 则跳过）",
    )
    args = ap.parse_args()

    if args.tex is None:
        ap.error("--tex is required")
    if args.bib is None:
        ap.error("--bib is required")

    required_fields = [f.strip() for f in args.required_fields.split(",") if f.strip()]

    summary, findings = run_audit(args.tex, args.bib, required_fields, args.todo_pattern)

    # Optional backends: merge their findings
    if args.use_biber_tool:
        findings.extend(biber_tool_validate(args.bib))

    if args.use_bibtool:
        findings.extend(bibtool_check(args.bib, args.todo_pattern))

    audit_id = f"bib-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if args.out:
        # --out provided: write JSON to the given path
        out_json = Path(args.out)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        json_obj = {
            "audit_id": audit_id,
            "tex": str(args.tex),
            "bib": str(args.bib),
            "summary": summary,
            "findings": findings,
        }
        out_json.write_text(json.dumps(json_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[报告] json -> {out_json}")
    else:
        # No --out: write <prefix>.md + <prefix>.json to audit/ directory
        out_default_dir = Path.cwd() / "audit"
        out_default_dir.mkdir(parents=True, exist_ok=True)
        out_prefix = out_default_dir / f"bib_audit_{datetime.now().strftime('%Y%m%d')}"
        md_text = render_md(audit_id, args.tex, args.bib, summary, findings)
        md_path = out_prefix.with_suffix(".md")
        json_path = out_prefix.with_suffix(".json")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_text, encoding="utf-8")
        json_obj = {
            "audit_id": audit_id,
            "tex": str(args.tex),
            "bib": str(args.bib),
            "summary": summary,
            "findings": findings,
        }
        json_path.write_text(json.dumps(json_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[报告] md   -> {md_path}")
        print(f"[报告] json -> {json_path}")

    print(f"[bib_audit] tex: {args.tex}")
    print(f"[bib_audit] bib: {args.bib}")
    print(f"[size] cite_keys={summary['cite_keys_in_tex']} entries={summary['entries_in_bib']}")
    print()

    error_count = summary["dangling_cite_count"] + summary["todo_placeholder_count"]
    warn_count = summary["unused_entry_count"] + summary["missing_field_count"]

    if summary["dangling_cite_count"]:
        print(f"[FAIL] dangling_cite: {summary['dangling_cite_count']} 处")
        for f in findings:
            if f.get("type") == "dangling_cite":
                print(f"    L{f['tex_line']}: \\cite{{{f['key']}}}")
    else:
        print("[ OK ] dangling_cite 0")

    if summary["todo_placeholder_count"]:
        print(f"[FAIL] todo_placeholder: {summary['todo_placeholder_count']} 处")
        for f in findings:
            if f.get("type") == "todo_placeholder":
                print(f"    bib L{f['bib_line']}: {f['key']}")
    else:
        print("[ OK ] todo_placeholder 0")

    if summary["unused_entry_count"]:
        print(f"[WARN] unused_entry: {summary['unused_entry_count']} 处")
        for f in findings:
            if f.get("type") == "unused_entry":
                print(f"    bib L{f['bib_line']}: {f['key']}")
    else:
        print("[ OK ] unused_entry 0")

    if summary["missing_field_count"]:
        print(f"[WARN] missing_field: {summary['missing_field_count']} 处")
        for f in findings[:10]:
            if f.get("type") == "missing_field":
                print(f"    bib L{f['bib_line']}: {f['key']} 缺 {f['field']}")
    elif required_fields:
        print("[ OK ] missing_field 0")

    if summary["commented_placeholder_count"]:
        print(f"[INFO] commented_placeholder: {summary['commented_placeholder_count']} 处 (注释中的 TODO 占位)")
        for f in findings:
            if f.get("type") == "commented_placeholder":
                print(f"    bib L{f['bib_line']}: {f['key']}")

    print()

    if error_count == 0 and warn_count == 0:
        print("[PASS] 引用一致性全部通过")

    sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()
