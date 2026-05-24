"""Generate compile.ps1 from Jinja2 template + subprocess driver."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def render_compile_ps1(paper_root: Path, paper_name: str = "paper") -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template("compile.ps1.j2")
    return tmpl.render(paper_root=str(paper_root), paper_name=paper_name)


def write_compile_ps1(paper_root: Path, paper_name: str = "paper") -> Path:
    rendered = render_compile_ps1(paper_root, paper_name)
    out = paper_root / "compile.ps1"
    out.write_text(rendered, encoding="utf-8")
    return out


def run_compile(paper_root: Path, paper_name: str = "paper", strict: bool = False) -> int:
    """直接调 latexmk（不必经 compile.ps1 壳，CLI compile 子命令使用）。"""
    if not shutil.which("latexmk"):
        raise RuntimeError("latexmk not in PATH (need latexmk >= 4.70)")
    latexmkrc = paper_root / ".latexmkrc"
    if not latexmkrc.exists():
        raise RuntimeError(f".latexmkrc not found; run `paper-agent init` first ({latexmkrc})")
    out_dir = paper_root / "out"
    out_dir.mkdir(exist_ok=True)
    tex = paper_root / "src" / f"{paper_name}.tex"
    result = subprocess.run(
        ["latexmk", "-r", str(latexmkrc), f"-outdir={out_dir}", str(tex)],
        cwd=str(paper_root / "src"),
        text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode
