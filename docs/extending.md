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

## 给 paper 加真值表（reverse_verify / number rule）

`reverse_verify` (0.1.1.dev) 把"正文里每个数字必须 100% 命中已发布报告"做成项目可配置的反推审计。引擎 paper-agnostic，每个 paper 在自己的 `paper_root/truth.json` 列关键真值即可。

1. 在 `<paper_root>/` 下新建 `truth.json`：
   ```json
   {
     "version": "0.1.1",
     "paper": {"id": "my-paper", "title": "..."},
     "items": [
       {
         "name": "样本量",
         "section": "3.1 数据",
         "candidates": ["N = 200", "N=200", "200 名"]
       }
     ]
   }
   ```
2. 跑 `paper-agent audit <paper_root>` —— number rule 自动启用（默认 `--rules` 已含 `number`）。若 `truth.json` 不存在则 silently skip（通用化承诺：不强制每个 paper 都有真值表）。
3. 任何 item 在 paper 正文中找不到任一 candidate → 1 个 ERROR `number_miss` finding。`--strict` 会阻断 compile。

匹配语义：
- LaTeX 行级 `%`-注释自动剥除（`\%` 字面百分号保留）
- 多 candidate 任一命中即 hit（覆盖千分位 `1,818,649` / 字面 `1818649` / LaTeX 转义 `1{,}818{,}649` 三种形式）
- `severity` 可 override 为 `WARN`/`INFO`（默认 `ERROR`）
- `section` 仅 informational，不参与匹配
