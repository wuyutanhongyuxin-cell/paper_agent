"""paper-agent CLI entry point."""
import argparse
import sys

from . import __version__
from ._util import reconfigure_utf8


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper-agent",
        description="Academic paper audit + Edit Gate pipeline.",
    )
    p.add_argument("--version", action="version", version=f"paper-agent {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False, metavar="<command>")

    sub.add_parser("init", help="Initialize a new paper project")
    sub.add_parser("audit", help="Run audit rules (read-only)")
    sub.add_parser("compile", help="Compile paper.tex via latexmk")
    sub.add_parser("apply", help="Apply staged diff (requires real TTY)")
    return p


def main(argv: list[str] | None = None) -> int:
    reconfigure_utf8()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    print(f"[paper-agent] {args.cmd} (not yet implemented in T2; see T11/T13)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
