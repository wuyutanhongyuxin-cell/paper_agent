"""paper-agent CLI entry point."""
import argparse
import sys
from pathlib import Path

from . import __version__
from ._util import reconfigure_utf8


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper-agent",
        description="Academic paper audit + Edit Gate pipeline.",
    )
    p.add_argument("--version", action="version", version=f"paper-agent {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False, metavar="<command>")

    init_p = sub.add_parser("init", help="Initialize a new paper project")
    init_p.add_argument("paper_root", type=Path)
    init_p.add_argument("--lang", default="zh", choices=["zh", "en", "ja"])
    init_p.add_argument(
        "--field",
        default="linguistics",
        choices=["linguistics", "medicine", "humanities", "cs", "sciences"],
    )
    init_p.add_argument("--paper-name", default="paper")

    audit_p = sub.add_parser("audit", help="Run audit rules (read-only)")
    audit_p.add_argument("paper_root", type=Path)
    audit_p.add_argument("--lang", default="zh", choices=["zh", "en", "ja"])
    audit_p.add_argument(
        "--rules",
        default="bib,punct,humanize",
        help="逗号分隔: bib / punct / humanize",
    )
    audit_p.add_argument(
        "--strict",
        action="store_true",
        help="ERROR-级 finding 返回非 0 (pre-compile hook 用)",
    )
    audit_p.add_argument("--paper-name", default="paper")

    compile_p = sub.add_parser("compile", help="Compile paper.tex via latexmk")
    compile_p.add_argument("paper_root", type=Path)
    compile_p.add_argument("--paper-name", default="paper")
    compile_p.add_argument(
        "--strict",
        action="store_true",
        help="pre-compile audit 失败时阻断",
    )

    apply_p = sub.add_parser("apply", help="Apply staged diff (requires real TTY)")
    apply_p.add_argument("--paper-root", required=True, type=Path)
    apply_p.add_argument("--diff-id", required=True, type=str)
    apply_p.add_argument("--paper-name", default="paper", type=str)
    return p


def main(argv: list[str] | None = None) -> int:
    reconfigure_utf8()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0

    if args.cmd == "init":
        from .compile.latexmkrc_gen import write_latexmkrc
        from .compile.compile_ps1 import write_compile_ps1
        from .core.config import PaperAgentConfig, ConfigError
        try:
            cfg = PaperAgentConfig.from_args(
                paper_root=args.paper_root,
                lang=args.lang,
                field=args.field,
                paper_name=args.paper_name,
            )
        except ConfigError as e:
            print(f"[FAIL] ConfigError: {e}", file=sys.stderr)
            return 1
        latexmkrc = write_latexmkrc(cfg.paper_root)
        ps1 = write_compile_ps1(cfg.paper_root, paper_name=args.paper_name)
        print(f"[init] {latexmkrc}")
        print(f"[init] {ps1}")
        print(f"[init] lang={cfg.lang} field={cfg.field}")
        return 0

    if args.cmd == "audit":
        from .core.edit_gate import audit
        rules = [r.strip() for r in args.rules.split(",") if r.strip()]
        findings = audit(
            args.paper_root,
            rules=rules,
            lang=args.lang,
            paper_name=args.paper_name,
        )
        errors = [f for f in findings if f.severity == "ERROR"]
        for f in findings:
            print(f"[{f.severity}] {f.rule} {f.file}:{f.line} {f.message}")
        print(f"\n[audit] {len(findings)} findings ({len(errors)} ERROR)")
        return 1 if args.strict and errors else 0

    if args.cmd == "compile":
        from .compile.compile_ps1 import run_compile
        # 0.1.0：pre-compile audit-gate 已在 .latexmkrc 的 $pre_compile_hook 注入
        code = run_compile(args.paper_root, paper_name=args.paper_name)
        return code

    if args.cmd == "apply":
        from .core.edit_gate import edit_gate, EditGateError
        try:
            result = edit_gate(args.paper_root, args.diff_id, paper_name=args.paper_name)
            print(f"[OK] applied {result.diff_id}")
            print(f"     archived -> {result.applied_dir}")
            print(f"     backup   -> {result.backup_path}")
            print(f"     post sha -> {result.post_apply_sha256}")
            return 0
        except EditGateError as e:
            print(f"[FAIL] {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        except FileNotFoundError as e:
            print(f"[FAIL] FileNotFoundError: {e}", file=sys.stderr)
            return 1

    print(f"[paper-agent] unknown cmd: {args.cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
