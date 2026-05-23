"""Config dataclass + validation.

spec §A.1 (5 学科白名单) + §C.1 (lang zh / en占位 / ja占位)。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_LANGS = frozenset({"zh", "en", "ja"})
SUPPORTED_FIELDS = frozenset({"linguistics", "medicine", "humanities", "cs", "sciences"})


class ConfigError(ValueError):
    """Raised when --lang / --field / --paper-root invalid."""


@dataclass(frozen=True)
class PaperAgentConfig:
    paper_root: Path
    lang: str
    field: str
    paper_tex: Path

    @classmethod
    def from_args(
        cls,
        paper_root: str | Path,
        lang: str,
        field: str,
        paper_name: str = "paper",
    ) -> "PaperAgentConfig":
        if lang not in SUPPORTED_LANGS:
            raise ConfigError(
                f"--lang={lang!r} not in {sorted(SUPPORTED_LANGS)} "
                "(en/ja 0.2.0+ placeholder)"
            )
        if field not in SUPPORTED_FIELDS:
            raise ConfigError(
                f"--field={field!r} not in {sorted(SUPPORTED_FIELDS)}"
            )
        root = Path(paper_root).resolve()
        if not root.exists():
            raise ConfigError(f"--paper_root={root} does not exist")
        if not root.is_dir():
            raise ConfigError(f"--paper_root={root} is not a directory")
        paper_tex = root / "src" / f"{paper_name}.tex"
        if not paper_tex.exists():
            raise ConfigError(f"paper.tex not found at {paper_tex}")
        return cls(paper_root=root, lang=lang, field=field, paper_tex=paper_tex)
