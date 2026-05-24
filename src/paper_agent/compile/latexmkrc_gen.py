"""Generate .latexmkrc from Jinja2 template."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def render_latexmkrc(paper_root: Path, rules: str = "bib,punct,humanize") -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template("latexmkrc.j2")
    return tmpl.render(paper_root=str(paper_root), rules=rules)


def write_latexmkrc(paper_root: Path, rules: str = "bib,punct,humanize") -> Path:
    rendered = render_latexmkrc(paper_root, rules)
    out = paper_root / ".latexmkrc"
    out.write_text(rendered, encoding="utf-8")
    return out
