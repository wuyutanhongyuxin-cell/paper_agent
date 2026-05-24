"""Lang-pluggable rule loader.

spec §B.3 audit/rules/{zh,en,ja}.py.
"""
from __future__ import annotations

import copy
from importlib import import_module

SUPPORTED_LANGS = ("zh", "en", "ja")


def load_rules(lang: str) -> dict:
    """Load rules dict for given language. en/ja are 0.2.0+ placeholders."""
    if lang not in SUPPORTED_LANGS:
        raise KeyError(f"lang={lang!r} not in {SUPPORTED_LANGS}")
    mod = import_module(f"paper_agent.audit.rules.{lang}")
    return copy.deepcopy(getattr(mod, "RULES", {}))
