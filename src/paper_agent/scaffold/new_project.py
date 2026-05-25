"""Generate paper.tex + references.bib skeleton from Jinja2 templates."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

SUPPORTED_LANGS = ("zh", "en")


class ScaffoldError(Exception):
    """Raised when the target paper_root state forbids scaffolding (refuse-to-overwrite)."""


@dataclass(frozen=True)
class ScaffoldResult:
    paper_tex: Path
    references_bib: Path


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )


def render_paper_tex(lang: str, field: str) -> str:
    if lang not in SUPPORTED_LANGS:
        raise ScaffoldError(
            f"unsupported lang for scaffolding: {lang!r}. Supported: {SUPPORTED_LANGS}. "
            f"For ja/other languages, copy tests/fixtures/non_aphasia_cs/src/ manually."
        )
    tmpl = _env().get_template(f"paper.tex.{lang}.j2")
    return tmpl.render(field=field, lang=lang)


def render_references_bib() -> str:
    tmpl = _env().get_template("references.bib.j2")
    return tmpl.render()


def write_paper_skeleton(
    paper_root: Path,
    lang: str = "zh",
    field: str = "linguistics",
    paper_name: str = "paper",
) -> ScaffoldResult:
    """Create <paper_root>/src/{<paper_name>.tex, references.bib} from templates.

    Refuses to overwrite an existing paper.tex or references.bib in the target
    src/ directory. Caller (CLI) is responsible for invoking init() afterwards
    to also write .latexmkrc + compile.ps1.

    Raises:
        ScaffoldError: if paper.tex or references.bib already exists, or lang unsupported.
    """
    paper_root = Path(paper_root).resolve()
    src = paper_root / "src"
    src.mkdir(parents=True, exist_ok=True)

    tex_path = src / f"{paper_name}.tex"
    bib_path = src / "references.bib"

    if tex_path.exists():
        raise ScaffoldError(
            f"refuse to overwrite existing file: {tex_path}. "
            f"Move or delete it first, or use `paper-agent init` (no scaffold)."
        )
    if bib_path.exists():
        raise ScaffoldError(
            f"refuse to overwrite existing file: {bib_path}. "
            f"Move or delete it first, or use `paper-agent init` (no scaffold)."
        )

    tex_path.write_text(render_paper_tex(lang, field), encoding="utf-8")
    bib_path.write_text(render_references_bib(), encoding="utf-8")

    return ScaffoldResult(paper_tex=tex_path, references_bib=bib_path)
