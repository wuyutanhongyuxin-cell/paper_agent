"""Rules registry: load_rules(lang) returns punct + humanize 词表。"""
import pytest

from paper_agent.audit.rules import load_rules, SUPPORTED_LANGS


def test_zh_rules_have_required_keys():
    r = load_rules("zh")
    for k in ("punct_patterns", "humanize_llm_traces", "humanize_ai_zh_words", "humanize_ai_en_words"):
        assert k in r, f"missing {k} in zh rules"
    assert len(r["humanize_ai_zh_words"]) >= 5
    assert "至关重要" in r["humanize_ai_zh_words"]


def test_en_rules_placeholder():
    r = load_rules("en")
    assert r == {} or all(not v for v in r.values())


def test_ja_rules_placeholder():
    r = load_rules("ja")
    assert r == {} or all(not v for v in r.values())


def test_unknown_lang_raises():
    with pytest.raises(KeyError):
        load_rules("es")
