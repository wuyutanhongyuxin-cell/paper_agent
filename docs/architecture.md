# paper-agent Architecture

> 本文档复用 `E:\claude_ask\.knowledge\specs\2026-05-23-paper-agent-design.md` 全部决策。
> Section A-G 完整设计 + cross-verification audit log 见原 spec。
> 后续随着 0.1.1 / 0.2.0 演进，本文档接管为活文档；spec 冻结为历史记录。

## TL;DR

- 两层：Layer 0 thin skill（chinese-academic-paper-rigor 重写为 ~150 行 wrapper）+ Layer 2 paper-agent pip 包
- Edit Gate 三层 API：audit (Layer 1 read-only) / advisory (Layer 2 read-only + 写 advisory/) / edit_gate (Layer 3 写盘，必经真实 TTY)
- 信任锚 = TTY 人类键入（删除 JWT/HS256；同进程 LLM agent 在密码学上无法区分人/agent，详见 spec §F.6）

## External dependencies

- Python >= 3.11
- jinja2 >= 3
- latexmk >= 4.70（spec §D.5: `$xelatex = "... %O %S"` 用 `%O` 自动注入 `-no-pdf`）
- biber（biber --tool --validate-datamodel backend, P1-7）
- bibtool（可选 todo-pattern backend, P1-7）
- MiKTeX 或 TeX Live
- chktex（可选 post-flight, informational）

## 详细模块设计

详见 spec §D。
