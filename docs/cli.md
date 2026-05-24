# paper-agent CLI 参考

## 子命令

### `paper-agent init <paper-root> --lang <lang> --field <field>`

初始化 paper 项目：生成 `.latexmkrc` + `compile.ps1`。

参数：
- `paper_root`：项目根目录（含 `src/paper.tex`）
- `--lang`：`zh` / `en` (placeholder) / `ja` (placeholder)
- `--field`：`linguistics` / `medicine` / `humanities` / `cs` / `sciences`
- `--paper-name`：默认 `paper`

### `paper-agent audit <paper-root> [--rules ...] [--lang ...] [--strict]`

跑 audit 规则（Layer 1 read-only）。输出 finding list 到 stdout 和 `audit/<run_id>/<rule>.json`。

参数：
- `--rules`：逗号分隔，可选 `bib` / `punct` / `humanize`（0.1.0 全 3 个）
- `--strict`：ERROR-级 finding 退出 1（pre-compile hook 用）

### `paper-agent compile <paper-root>`

调 `latexmk` 编译 `paper.tex` → `out/paper.pdf`。
内部经 `.latexmkrc` 的 `$pre_compile_hook` 自动跑 `paper-agent audit --strict`。

### `paper-agent apply --paper-root <root> --diff-id <id>`

**必须在真实终端运行。** 应用 advisory/<diff_id>/ 中的 patch 到 paper.tex。
信任锚 = TTY 人类键入 y/n/q。

详见 architecture.md / spec §D.1。
