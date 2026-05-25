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

详见 spec §D.2。0.1.0 之外的规则（`fig_audit` / `stat_audit` / `sample_audit` 已落地，`related_work_audit` 仍在 0.1.1 PaperQA2 spike 阶段）。

## fig_audit / figure rule（0.1.1.dev M-B.1）

针对 LaTeX `\begin{figure}[*]...\end{figure}[*]` 环境检查 3 项：

| 检测项 | 严重度 | 触发条件 |
|--------|--------|---------|
| `label_duplicate` | ERROR | 两个 figure 环境内出现相同 `\label{fig:X}` |
| `caption_too_short` | WARN | `\caption{...}` 字符数 < 20 |
| `orphan_figure` | WARN | figure 内的 `\label{fig:X}` 没有任何 `\ref/\autoref/\cref/\Cref/\Vref` 反向引用 |
| `chktex_warn` | INFO | 可选: `--use-chktex` 调外部 chktex（不在 PATH 则 silently skip） |

CLI:
```bash
python -m paper_agent.audit.rule.fig_audit --tex paper.tex --out audit/fig.json
python -m paper_agent.audit.rule.fig_audit --tex paper.tex --use-chktex --out audit/fig.json
```

或通过统一 audit 入口（`paper-agent audit <root>` 默认 `--rules` 已含 `figure`）。

## stat_audit / stat rule（0.1.1.dev M-B.2）

针对统计报告格式做 4 类检查；与 reverse_verify 正交（reverse_verify 知道具体数字，stat_audit 不知道但查 APA-style 完整性）：

| 检测项 | 严重度 | 触发条件 |
|--------|--------|---------|
| `p_value_out_of_range` | ERROR | `p = X` / `p < X` / `p > X` 中 X ∉ [0, 1] |
| `anova_missing_F/df/p` | WARN | ANOVA 块（含 `ANOVA` 或 `F(...)` 关键词）缺 F/df/p 任一 |
| `anova_missing_eta/N` | INFO | ANOVA 块缺效应量（η²/Cohen d 等）或 N |
| `mean_missing_sd_or_n` | WARN | 段含 mean/M= 但缺 SD/标准差（N 不算替代） |
| `ci_missing_bounds` | WARN | 段含 `CI` / `置信区间` 但无 `[lo, hi]` 形式 |

**注**：本 rule 与失语症 paper "ANOVA 三个 p > 0.10" hard constraint 正交：王老师约束是 p **数值**，stat_audit 是 p **格式** ∈ [0, 1]。0.10 ∈ [0, 1] 始终通过 stat_audit。

CLI:
```bash
python -m paper_agent.audit.rule.stat_audit --tex paper.tex --out audit/stat.json
```

## sample_audit / sample rule（0.1.1.dev M-B.3）

抽 N 段 paper.tex 正文 paragraph，每段生成一份 paper-agnostic 人工复核 prompt 模板（INFO 级别，**永不阻断** compile 退出码）。

设计动机：在 LLM 评分之外，每次 audit 都强制人类抽查 N 段，防止全程 LLM-only 形成审计盲区。本 rule 不调任何 LLM，prompt 模板不 hardcode 学科特异术语。

| 参数 | 默认 | 说明 |
|------|------|------|
| `--n` | 3 | 抽段数 |
| `--seed` | 42 | 随机种子（保证 audit 可重现） |

CLI:
```bash
python -m paper_agent.audit.rule.sample_audit --tex paper.tex --n 5 --seed 42 --out audit/sample.json
```

paragraph 提取规则：
- 空行分隔的非空文本块
- 跳过 `\section/\subsection/\subsubsection` 等结构命令开头的行
- 跳过 `figure/table/equation/align/itemize/enumerate/verbatim/lstlisting/minted/tikzpicture/tabular` 环境内段落
- 跳过 < 30 字符的过短段
- LaTeX `%`-注释剥除后再分段

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
