# Extending paper-agent

## 加一种新语言

1. `src/paper_agent/audit/rules/<lang>.py`：填 `RULES` dict（仿照 `zh.py`）
2. `src/paper_agent/audit/rule/punct_audit.py` 等：检查 lang-pluggable 规则是否复用了 `RULES["punct_patterns"]`
3. `tests/fixtures/min_linguistics_<lang>.tex`：合规 fixture
4. 跑 `pytest tests/test_rules_registry.py` 验证

## 加一种新学科

1. `src/paper_agent/core/config.py`：扩 `SUPPORTED_FIELDS`
2. `tests/fixtures/min_<field>_zh.tex` + `.bib`：合规 fixture
3. `tests/test_golden_papers.py`：在 `parametrize` 中加 `<field>`

## 加一条新 audit 规则

详见 spec §D.2。0.1.0 之外的规则（`fig_audit` / `stat_audit` / `related_work_audit` / `sample_audit`）规划在 0.1.1。
