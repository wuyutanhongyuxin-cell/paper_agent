# Changelog

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
