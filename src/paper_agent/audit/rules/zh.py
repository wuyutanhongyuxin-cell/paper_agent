"""中文规则集（punct_audit P1-P7 (P8-P9 deferred to 0.2.0+) + humanize_check R1-R7 字符级规则）。

迁入自 chinese-academic-paper-rigor skill humanize_check.py.template + weiwuer/punct_audit.py。
通用化：词表与规则代码解耦；学科特异规则归 projects/<name>/rules/。
"""

# R1 LLM 痕迹（正则）
HUMANIZE_LLM_TRACES = r"agent|LLM|AI|大模型|生成式|chatgpt|claude|gemini|gpt-"

# R2 AI 高频中文词（含 lookahead 放过 L-046 attribution）
HUMANIZE_AI_ZH_WORDS = [
    "本文",         # 后接非"为/，/："
    "本研究",       # 同上
    "至关重要",
    "旨在",
    "推动",
    "综上所述",
    "总而言之",
    "不仅...而且",
    "核心要义",
    "赋能",
    "破局",
    "毋庸置疑",
    "此外",         # AI 衔接词典型
]

# R3 AI 高频英文词
HUMANIZE_AI_EN_WORDS = [
    "delve", "pivotal", "unlock", "facilitate", "leveraging", "robust",
]

# punct_audit P1-P7 中文段标点规则（U+ 编码注释见 weiwuer/punct_audit.py）
PUNCT_PATTERNS = {
    "P1_ascii_double_quote_in_cn": "\"",        # ASCII U+0022
    "P2_japanese_corner_quote":    "「」",  # U+300C/U+300D — MUST be exactly 2 chars (open+close)
    "P3_cn_curly_quote_pair":      "“”",  # U+201C/U+201D — MUST be exactly 2 chars (open+close)
    "P4_ascii_single_quote_in_cn": "'",         # ASCII U+0027
    "P5_halfwidth_comma_in_cn":    ",",         # U+002C
    "P6_halfwidth_semicolon_in_cn": ";",        # U+003B
    "P7_halfwidth_colon_in_cn":    ":",         # U+003A
}

RULES = {
    "punct_patterns": PUNCT_PATTERNS,
    "humanize_llm_traces": HUMANIZE_LLM_TRACES,
    "humanize_ai_zh_words": HUMANIZE_AI_ZH_WORDS,
    "humanize_ai_en_words": HUMANIZE_AI_EN_WORDS,
}
