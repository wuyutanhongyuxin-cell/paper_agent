"""paper-agent CLI entry point."""
import argparse
import sys

from . import __version__
from ._util import reconfigure_utf8


def _build_parser() -> argparse.ArgumentParser:
    from pathlib import Path

    p = argparse.ArgumentParser(
        prog="paper-agent",
        description="Academic paper audit + Edit Gate pipeline.",
    )
    p.add_argument("--version", action="version", version=f"paper-agent {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False, metavar="<command>")

    sub.add_parser("init", help="Initialize a new paper project")
    sub.add_parser("audit", help="Run audit rules (read-only)")
    sub.add_parser("compile", help="Compile paper.tex via latexmk")

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
    print(f"[paper-agent] {args.cmd} (placeholder; T13 implements init/audit/compile)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
