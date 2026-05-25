# Changelog

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
