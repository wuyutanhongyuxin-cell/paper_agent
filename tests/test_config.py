"""Config validation: --lang / --field / --paper-root white-listed."""
from pathlib import Path

import pytest

from paper_agent.core.config import (
    PaperAgentConfig,
    SUPPORTED_LANGS,
    SUPPORTED_FIELDS,
    ConfigError,
)


def test_supported_constants_match_spec():
    """spec §C.1 + §A.1: 5 学科 + 3 语言（en/ja 占位）。"""
    assert SUPPORTED_FIELDS == {"linguistics", "medicine", "humanities", "cs", "sciences"}
    assert SUPPORTED_LANGS == {"zh", "en", "ja"}


def test_valid_config(tmp_path):
    paper_root = tmp_path / "paper"
    (paper_root / "src").mkdir(parents=True)
    (paper_root / "src" / "paper.tex").write_text(r"\documentclass{article}", encoding="utf-8")
    cfg = PaperAgentConfig.from_args(
        paper_root=str(paper_root),
        lang="zh",
        field="linguistics",
    )
    assert cfg.lang == "zh"
    assert cfg.field == "linguistics"
    assert cfg.paper_root == paper_root


def test_invalid_field_raises():
    with pytest.raises(ConfigError, match="field"):
        PaperAgentConfig.from_args(paper_root=".", lang="zh", field="biology")


def test_invalid_lang_raises():
    with pytest.raises(ConfigError, match="lang"):
        PaperAgentConfig.from_args(paper_root=".", lang="es", field="linguistics")


def test_missing_paper_root_raises(tmp_path):
    with pytest.raises(ConfigError, match="paper_root"):
        PaperAgentConfig.from_args(
            paper_root=str(tmp_path / "does-not-exist"),
            lang="zh",
            field="linguistics",
        )


def test_paper_tex_default_inferred(tmp_path):
    paper_root = tmp_path / "p"
    (paper_root / "src").mkdir(parents=True)
    (paper_root / "src" / "paper.tex").write_text("x", encoding="utf-8")
    cfg = PaperAgentConfig.from_args(paper_root=str(paper_root), lang="zh", field="linguistics")
    assert cfg.paper_tex == paper_root / "src" / "paper.tex"
