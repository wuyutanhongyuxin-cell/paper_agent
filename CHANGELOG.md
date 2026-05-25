# Changelog

## [Unreleased]

### Added (M-B Light audits — spec §D.2 / 0.1.1 路线图 M-B)
- `paper_agent.audit.rule.fig_audit` — 图（figure）一致性审计：`label_duplicate` (ERROR) / `caption_too_short` (WARN, < 20 字符) / `orphan_figure` (WARN, label 无 `\ref` 反向覆盖) / 可选 `chktex_warn` (INFO, `--use-chktex` flag). CLI `python -m paper_agent.audit.rule.fig_audit --tex ... --out ...json`. 注册到 `_RULE_MODULE_MAP` 的 `"figure"`. 21 个单元测试覆盖 strip_comments / find_figure_envs / extract_labels / extract_caption (balanced-brace + `\caption[short]{long}`) / find_ref_keys (\\ref/\\autoref/\\cref/\\Cref/\\Vref) / 三 rule semantics / `figure*` 支持 / 中文 caption / `\label` 在 figure 环境外不参与判定.
- `paper_agent.audit.rule.stat_audit` — 统计报告格式审计：`p_value_out_of_range` (ERROR, p ∉ [0,1]) / `anova_missing_F|df|p` (WARN) / `anova_missing_eta|N` (INFO) / `mean_missing_sd_or_n` (WARN, mean 段必须有 SD) / `ci_missing_bounds` (WARN, CI 段必须有 `[lo,hi]`). 与 reverse_verify 正交（reverse_verify 知道具体数字，stat_audit 查 APA-style 格式完整性）. 与失语症 paper 王老师 "ANOVA 三个 p > 0.10" hard constraint 不冲突（王老师查数值，stat_audit 查 ∈ [0,1] 数学合法性，0.10 始终通过）. 27 个单元测试.
- `paper_agent.audit.rule.sample_audit` — 抽 N 段人工复核 prompt 模板（INFO 级别，**永不阻断** rc）. `--n 3 --seed 42` 默认（保证 audit 可重现）. paragraph 过滤: 空行分隔 / 跳过 `\\section/\\subsection/\\subsubsection` / 跳过 `figure/table/equation/align/itemize/enumerate/verbatim/lstlisting/minted/tikzpicture/tabular` 环境内 / 跳过 < 30 字符过短段. prompt 模板 paper-agnostic (无 hardcode 学科特异术语). 14 个单元测试.
- `core/edit_gate.py::_RULE_MODULE_MAP` 注册三个新 rule (`figure` / `stat` / `sample`); `audit()` for-loop dispatch 添加三个 rule 的 extra_args 构造分支 (均仅传 `--tex --lang --out`, 不需要额外配置).
- `cli.py` audit subparser `--rules` 默认从 `"bib,punct,humanize,number"` 扩到 `"bib,punct,humanize,number,figure,stat,sample"` (7 rule 全开). help 文字明确 `sample` 始终 INFO 级不阻断退出码.
- `docs/extending.md` 新增三个 rule 的 section: detection table / CLI usage / paragraph 提取规则 (sample_audit).

### Added (M-A reverse_verify 通用化)
- `paper_agent.audit.rule.reverse_verify` 通用化"真值反推"审计（spec §C.2 / 0.1.1 路线图 M-A）—— 把 `number_audit.py` 硬编码 28 项失语症 TRUTH dict 通用化为 `<paper_root>/truth.json` 外部配置驱动。引擎完全 paper-agnostic，每个 paper 自管真值表（[[feedback_paper_agent_long_term_generality]] 长期通用化承诺的关键一环）。
  - `src/paper_agent/audit/rule/reverse_verify.py` — CLI `--tex --truth --lang --out`，schema 校验 + 行级 %-注释剥除（与 number_audit.py 等价语义）+ 多 candidate OR 匹配 + severity override（ERROR/WARN/INFO）。
  - `core/edit_gate.py::_RULE_MODULE_MAP` 注册 `"number"` rule；`audit()` 分发：`paper_root/truth.json` 不存在则 **silently skip**（通用化考虑：不是所有 paper 都有真值表）。
  - `cli.py` audit subparser `--rules` 默认从 `"bib,punct,humanize"` 扩到 `"bib,punct,humanize,number"`。
- `tests/test_reverse_verify.py` 18 个单元测试（strip_tex_comments / load_truth schema 校验 / run_audit hit/miss/override/comment/escaped-percent/lang-independent/metadata）。
- `tests/integration/test_reverse_verify_e2e.py` 5 个 e2e：truth 缺失 silently skip / 全 hit 0 finding / miss → ERROR / `--rules number` 单独跑 / L-033 read-only。

### Migrated (DEPRECATED)
- `weiwuer/paper/tools/number_audit.py` 加 DEPRECATED banner（2026-06-25 sunset，与 0.1.0 GA 三件套 bib/punct/humanize_check 同序列；对账期 1 个月）。同步迁出 28 项失语症真值到 `weiwuer/paper/truth.json`。
- 替代命令：`paper-agent audit weiwuer/paper --rules number`（实跑：28/28 命中，与原 `number_audit.py` 跑出 `[PASS] 数字反推 100% 命中` 字节级等价）。

### Verified
- 全套 pytest：**98 passed + 2 skipped (latexmk only)** 0 failed（vs 0.1.1.dev0 baseline 75 → 98, +23 = 18 unit + 5 e2e）。
- `paper-agent audit weiwuer/paper --lang zh` 真跑：4 findings (3 INFO commented_placeholder + 1 WARN unused_entry) 0 ERROR — **未引入任何 number_miss**，与 0.1.0.post2 baseline 完全一致。
- 直接跑 `python -m paper_agent.audit.rule.reverse_verify --tex weiwuer/paper/src/paper.tex --truth weiwuer/paper/truth.json`：`[PASS] 真值反推 28/28 命中`。

## [0.1.1.dev0] - 2026-05-25

> Dev release — 朝 0.1.1 stable 演进中。已落地：`paper-agent new` scaffold 子命令、cross-field e2e fixture (non_aphasia_cs)、parity test 正常化重写。仍待 0.1.1 stable：4 条新 audit 规则 (fig/stat/related_work/sample) + 7 维评分 + Krippendorff α + halt rules + `reverse_verify.py` 通用化。

### Added
- `paper-agent new <paper_root> --lang zh|en --field <one of 5>` 子命令 — 一键生成完整空白论文项目（`src/paper.tex` + `src/references.bib` + `.latexmkrc` + `compile.ps1`），把"起新论文要手抄模板"盲点彻底补掉。
  - `src/paper_agent/scaffold/{__init__.py,new_project.py}` — jinja2 模板渲染 + refuse-to-overwrite 守卫（feedback_no_overwrite_source 硬约束：既有 `paper.tex` / `references.bib` 一律 `ScaffoldError`，绝不覆盖用户在编草稿）。
  - `src/paper_agent/scaffold/templates/paper.tex.zh.j2` — `\documentclass[zihao=-4,UTF8,fontset=fandol]{ctexart}` + biblatex backend=biber style=numeric + 4 section（Abstract + 引言 + 方法 + 结果 + 结论）+ References；包导入顺序严格 `graphicx → amsmath → amssymb → biblatex → hyperref(hidelinks)`；学科专用包（listings/tipa/siunitx/csquotes）以注释保留待 4 学科按需启用；中文国标投稿 `style=gb7714-2015` 切换提示注释。骨架本身跑 audit `0 findings (0 ERROR)`，不踩 R1-R7 / P1-P9 任何雷区。
  - `src/paper_agent/scaffold/templates/paper.tex.en.j2` — `\documentclass[11pt,a4paper]{article}` + 同款 biblatex 配置 + 4 section（Abstract + Introduction + Methods + Results + Conclusion）；`newtxtext,newtxmath` Times 字体以注释保留；hidelinks 默认 + 预印本 colorlinks 切换提示。
  - `src/paper_agent/scaffold/templates/references.bib.j2` — 1 条 `@misc{example_remove_me}` 占位（首编译全绿，biber 不报 "Empty database"；用户加真引用前删除）。
  - `tests/integration/test_new_e2e.py` — 9 个 e2e 测试：zh/en 各自全骨架生成、ctexart 文档类断言、paper.tex/references.bib 各自 refuse-overwrite、zh/en 各自跑 audit `0 findings (0 ERROR)`、L-033 read-only 守卫、ja 走 argparse 拒绝。
- `pyproject.toml` 注册 `paper_agent.scaffold.templates` 到 `[tool.setuptools.package-data]`，保证 `pip install` ship 模板文件。

### Fixed
- `tests/integration/test_aphasia_e2e.py` 3 个 parity 测试在真环境跑 byte-level stdout 比较时假报 regression（NEW 工具新增 `--lang zh` banner、`findings 已写入` 路径提示、`[INFO] D1/D2` 全角空格 advisory，OLD 工具均无；spec §C.1 Done #1 contract 本意是 finding 语义一致而非 stdout byte 一致）。
  - 重写 `_normalize_log` 为 `_extract_findings(text) -> list[tuple[str, str]]` + `_assert_parity(tool, old_stdout, new_stdout)`。提取 `(tag, rule_code)` 二元组，tag = `OK|FAIL|WARN|INFO|ERROR`；rule_code 用**显式 ASCII** `[A-Za-z][A-Za-z0-9_]*` 抓取，遇非 ASCII 立即停（覆盖 humanize_check `R1_LLM痕迹` 在 cp936 subprocess 输出里 mojibake 为不同 latin escape 的退化）。
  - 断言契约：NEW findings 过滤为 OLD 出现过的 rule_code 子集 → 与 OLD 严格相等。NEW 可新增 rule（不强制 OLD 覆盖），但 OLD 已有 rule 不允许丢失或 tag 变化。装饰行（`[bib_audit]` / `[size]` / `[报告]` / `[PASS]`）namespace 与 finding tag 不同，自然被滤除。
  - 详见 `tasks/lessons.md` L-050。

### Added
- `tests/fixtures/non_aphasia_cs/src/{paper.tex,references.bib}` — k-NN ANN 算法 HNSW vs IVF-PQ 实证比较小论文（cs 领域，与失语症 / 词汇研究 / 维吾尔语无任何关联），设计为完全干净（0 findings / 0 ERROR）。
- `tests/integration/test_non_aphasia_e2e.py` — 5 个 e2e 测试：fixture_present / audit_zero_findings / audit_strict_passes / audit_is_read_only (L-033) / init_cs_field_succeeds。回归保护 paper-agent 跨学科可消费的通用化承诺（spec §A.3 第五原则）。
- 补 long-term generality e2e 证据缺口：之前 5 个 `min_*.tex` 仅覆盖**单元**违例 fixture，端到端只有失语症 paper，0.1.0 通用化只在单元层有证据，e2e 层没有。

### Verified
- 真环境（PowerShell + Python 3.13）跑 `pytest tests/`: **75 passed + 2 skipped (latexmk)** 0 failed (66 → 75, +9 scaffold e2e)
- `paper-agent new <tmp> --lang zh --field cs` 真跑：4 个文件全生成；接续 `paper-agent audit <tmp> --lang zh` → **0 findings (0 ERROR)**，骨架自身完全合规
- `paper-agent audit E:\claude_ask\Notion\weiwuer\paper --lang zh` 真跑：4 findings (3 INFO commented_placeholder TODO_ref8/9/10 + 1 WARN unused_entry he2018meldsch) 0 ERROR — 与 `.knowledge/audits/paper-agent_spec-compliance_2026-05-25.md` 完全一致

---

## [0.1.0.post2] - 2026-05-25

### Fixed (docs)
- `README.md` 4 处事实失真（精装版重写时凭印象描述未对账代码）：
  - **`punct_audit` 表**：P1-P7 描述全部张冠李戴 → 改为按 `audit/rules/zh.py` `PUNCT_PATTERNS` 字面（P1=ASCII"、P2=「」、P3=""配对、P4=ASCII'、P5=半角逗号、P6=半角分号、P7=半角冒号）；补 P8 数学环境闭合 + P9 悬空 `\ref` 类（实际代码有，README 漏标）
  - **`humanize_check` 表**：R6/R7 凭空捏造（"副词典型 / 句长方差"） → 改为实际 R6 千分位被全角化 / R7 章节标号双角；R5 半角括号语义补全；补 R8 数字反查（advisory，`--data-source`）
  - **红队 T1-T6 表**：6 项描述与 `test_edit_gate.py` 实际**无一对应** → 改为按真实测试函数 (T1 NonInteractiveSession / T2 FileMutatedSinceAdvisory / T3 missing advisory / T4 PatchContextMismatch / T5 UserDenied / T6 concurrent flock)
  - **0.1.1 路线图**：凭空虚构 humanize R8-R10 段落语义重复度/情感色彩/自引用 → 改为按 spec §D.2 / §C.2 真实承诺（4 条新 audit 规则 fig/stat/related_work/sample + 7 维评分 + Krippendorff α + halt rules + `reverse_verify.py` 通用化）
- 行数统计纠正：bib_audit 440→537 行 / punct_audit 347→421 行 / humanize_check 293→383 行（精装版引用迁入前 plan 预算，实际迁入时已扩展 22-31% — 全部在 spec §D.2 0.1.0 能力范围内）

### Added
- `tests/test_edit_gate.py::test_t3a_stdin_pipe_spoofing_blocked` — plan 原意红队 T3（stdin pipe spoofing）专项测试。子进程 `subprocess.run(..., input="y\\n")` 模拟攻击者预喂 "y" 数据，断言 TTY guard 必抛 `NonInteractiveSession` 且 `paper.tex` 不被改动。
  - 之前 T3 偷换为 `test_t3_missing_advisory`（FileNotFoundError），攻击面仅通过 T1 + `test_cli.py::test_apply_in_non_tty_reports_non_interactive` 间接覆盖。post2 补回显式测试。

### Verified
- 仓库 spec 合规审计：`.knowledge/audits/paper-agent_spec-compliance_2026-05-25.md`（28 项 ✅ / 9 项 🟡 / 5 项 ❌ 中 4 项为本次修 README，1 项 staged/ 简化保留为 0.1.1 待办）

---

## [0.1.0.post1] - 2026-05-25

### Fixed
- `compile/templates/latexmkrc.j2`: 删除 `$biber = "biber --output-directory=%O %O %S";` 一行。
  - 症状：`paper-agent compile` 在 paper_root/out/ 干净（无旧 `.bbl`）时，biber 必失败 (return code 2)，latexmk exit 12。
  - 根因：`%O` 是 latexmk 给 LaTeX 引擎（xelatex/pdflatex）的占位符约定，会被注入 `-output-directory` `-recorder` 等；biber 不是 LaTeX 引擎，latexmk 不 inject 任何东西 → `--output-directory=%O` 字面展开为 `--output-directory= ` → biber 报 "Option output-directory requires an argument"。
  - 修复：删该行，回落到 latexmk 默认 `biber %O %S`。`-outdir` 已通过 latexmk cmdline 传递，biber 读 `.bcf` 自动找到 outdir。
  - 影响：之前已 init 的 paper 项目，需手改 `<paper_root>/.latexmkrc` 删该行；或重跑 `paper-agent init <paper_root>` 重生成。

### Verified
- 失语症 paper 真实编译：`latexmk` 全链路 (xelatex → biber 真跑 → xelatex×2 → xdvipdfmx) 跑通，`out/paper.pdf` 出 (~331 KB, 18 页)。
- MiKTeX 25.12 + Strawberry Perl 5.42.2.1 + biber 2.21 + latexmk 4.88 Windows 11 验证。

## [0.1.0] - 2026-05-24

### Added
- `paper-agent` CLI: `init` / `audit` / `compile` / `apply`
- 3 个 audit 规则：`bib_audit` (440 行迁入) / `punct_audit` (347 行迁入) / `humanize_check` (293 行迁入)
- Edit Gate 三层网关（TTY 信任锚 + flock + patch --strict + staged/applied/.bak）
- 红队 T1-T6 测试覆盖
- latexmk 替代 4-pass 手写编译（`.latexmkrc` $pre_compile_hook 注入 audit-gate）
- 5 学科 fixtures + Windows cp936 regression
- 失语症 paper golden snapshot (`golden_papers/aphasia-zh-0.1.0/`)

### Migrated from `weiwuer/paper/tools/`
- 3 个通用 audit 工具迁入 paper-agent；旧文件标 DEPRECATED 1 个月（2026-06-24 删除）
- `number_audit.py` 保留原状（paper-specific TRUTH dict）
- 旧 `compile.ps1` 改 1 行 shim 调 `paper-agent compile`；原版备份为 `compile.ps1.pre-0.1.0`

### Security
- 删除 JWT/HS256/keyring 层（同进程 LLM agent 同代码同 secret，密码学不可区分人/agent；详见 spec §F.6）
- TTY 信任锚替代（`sys.stdin.isatty() and sys.stdout.isatty()` + `/dev/tty` / `CON` 直读）
- TOCTOU 防护：排他 flock + 持锁内重算 sha256
