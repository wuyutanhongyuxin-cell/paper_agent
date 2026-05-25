# paper-agent

> 学术论文审计 + Edit Gate 流水线 — 让 LLM 帮你写论文，但永远不让它**直接落盘** `paper.tex`。

[![Version](https://img.shields.io/badge/version-0.1.0.post1-blue.svg)](./CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-59%20passing-brightgreen.svg)](./tests)
[![Real PDF](https://img.shields.io/badge/E2E-aphasia%20paper%20PDF%20verified-success.svg)](./tests/integration)

---

## 一句话

**LLM agent 可以审计、提议、staged，但 `paper.tex` 的写入路径**只有一条**：真实人类在真实终端键入 `y`。**

```
   LLM agent ──[audit / advisory]──> finding.json / advisory/<diff_id>/
                                              │
                                              ▼
                              ┌──── Edit Gate (Layer 3) ────┐
                              │  TTY isatty + /dev/tty 直读 │
                              │  + flock 排他锁              │
                              │  + sha256 TOCTOU 防护        │
                              └─────────────┬────────────────┘
                                            │ 通过
                                            ▼
                                       paper.tex
```

---

## 目录

- [这是什么](#这是什么)
- [为什么需要它](#为什么需要它)
- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [架构总览](#架构总览)
- [CLI 参考](#cli-参考)
- [Edit Gate 三层网关](#edit-gate-三层网关)
- [审计规则](#审计规则)
- [编译流水线](#编译流水线)
- [学科与语言支持](#学科与语言支持)
- [项目结构](#项目结构)
- [测试](#测试)
- [外部依赖](#外部依赖)
- [安装故障排查](#安装故障排查windows)
- [路线图](#路线图)
- [设计哲学](#设计哲学)
- [License](#license)

---

## 这是什么

`paper-agent` 是一个**面向 LLM 协作写论文**的 Python 工具链。它把"AI 改论文"这件事拆成两件事：

| 责任 | 谁来做 | 怎么做 |
|------|--------|--------|
| **审计 / 提议** | LLM agent | 跑 `paper-agent audit` → 读 finding；跑 `advisory` 接口 → 写 `advisory/<diff_id>/` 暂存补丁 |
| **落盘到 `paper.tex`** | **真实人类** | 在真实终端跑 `paper-agent apply --diff-id <id>`，键入 `y/n/q` |

中间隔着 **Edit Gate 三层网关**——这是 paper-agent 唯一的、不可绕过的写盘路径。

---

## 为什么需要它

直接让 LLM 改你的 `paper.tex`，你会遇到这些问题：

| 症状 | 频度 | 难发现度 |
|------|------|---------|
| AI 高频词渗透（"至关重要" "综上所述" "毋庸置疑" "推动……发展" 等十几个） | 极高 | 难（人读不一定觉察） |
| 中文段半角逗号 / 括号未全角化 | 高 | 难（视觉接近） |
| 千分位数字被错改成全角逗号（`1,818,649` → `1，818，649`）数学错误 | 中 | 极难 |
| 引用键 `\cite{}` 与 `.bib` 不同步、孤儿 entry | 中 | 中 |
| LLM 在引用里**伪造**作者 / 项目方法论 / 资源致谢 | 中 | **极难** |
| 编号字段（cell 数、词数、p 值）被无声修改 | 低但致命 | 极难 |
| LLM 在改 A 段时**顺手改坏** B 段 | 中 | 难 |
| **无法事后审计**到底改了什么 / 谁改的 / 哪一刻改的 | 100% | — |

`paper-agent` 把这些全部转成**机器可检的 finding** + **不可绕过的写盘网关**：

- LLM 不能直接 `Edit paper.tex` — 它没有那条路径
- LLM 唯一能做的是 `audit` 报警 + 把 patch 暂存到 `advisory/`
- 你（人类）在真实终端复核 staged 的 diff，键入 `y` 才落盘
- 全过程留下 `audit/` + `staged/` + `applied/` + `.bak` 四份审计痕迹

---

## 核心特性

### 1. CLI 四个子命令，覆盖全周期

```bash
paper-agent init     <root> --lang zh --field linguistics  # 初始化项目（生成 .latexmkrc / compile.ps1）
paper-agent audit    <root> --rules bib,punct,humanize     # 只读审计（LLM 可跑）
paper-agent compile  <root>                                # 编译 PDF（内嵌 pre-flight audit-gate）
paper-agent apply    --paper-root <root> --diff-id <id>    # 落盘（必经真实 TTY）
```

### 2. 三条 0.1.0 审计规则（共 ~1080 行迁入代码）

| 规则 | 行数 | 检查项 |
|------|------|--------|
| `bib_audit`     | 440 | `\cite{}` 引用键完整性 / 孤儿 entry / GB/T 7714 风格 / biber 验证 |
| `punct_audit`   | 347 | P1–P7：半角→全角、千分位保护、中英括号配对、ARROW 残留、引号成对 |
| `humanize_check`| 293 | R1–R7：LLM 痕迹词、AI 高频中英文词、模板套话、致谢段伪造检测 |

### 3. Edit Gate 三层网关（TOCTOU-safe）

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1  audit()       只读，返回 finding list                  │
│                        ↓ LLM 可调用                              │
│ Layer 2  advisory()    只读 + 写 advisory/<diff_id>/            │
│                        ↓ LLM 可调用                              │
│ Layer 3  edit_gate()   写 paper.tex，唯一路径                    │
│                        ▲ 必须人在真实 TTY                         │
│                        ▲ 必须持有排他 flock                      │
│                        ▲ 必须持锁内 sha256 复算（防 TOCTOU）       │
└─────────────────────────────────────────────────────────────────┘
```

### 4. latexmk 替代手写 4-pass（spec §D.5）

旧版 `compile.ps1` 是 130 行手写的 xelatex×3 + biber×1。0.1.0 改用 latexmk + Jinja2 模板：

- `$pdf_mode = 5` (xelatex + xdvipdfmx 两步流程)
- `$xelatex = "xelatex -interaction=nonstopmode -synctex=1 %O %S"` （`%O` 触发 latexmk 自动注入 `-no-pdf`，manpage v4.88 documented contract）
- `$pre_compile_hook` 强制注入 `paper-agent audit --strict`，审计不过编译就不开始

### 5. 真实端到端验证

`tests/integration/test_aphasia_e2e.py` 用真实的失语症词汇筛选论文 fixture 跑 `paper-agent compile`：

- ✅ xelatex → biber → xelatex×2 → xdvipdfmx 全 pass 跑通
- ✅ `out/paper.pdf` 真出 PDF（~331 KB / 18 页）
- ✅ 已验证平台：MiKTeX 25.12 + Strawberry Perl 5.42.2.1 + biber 2.21 + latexmk 4.88 / Windows 11

### 6. 红队测试 T1–T6

`tests/test_edit_gate.py` 专门为 Edit Gate 写了 6 个攻击场景：

| 编号 | 攻击 | 期望防御 |
|------|------|---------|
| T1 | LLM 在 `paper.tex` 落盘瞬间篡改文件（TOCTOU） | 持锁内 sha256 复算，不一致即拒绝 |
| T2 | LLM 调用 `apply` 但 stdin 是 pipe（伪 TTY） | `isatty()` 不通过即拒绝 |
| T3 | LLM 抢占 flock 持锁不释放 | `LOCK_NB` + 5s 超时拒绝 |
| T4 | `advisory/<diff_id>/` patch 被 LLM 写入恶意内容（绕过 audit） | `patch --strict --dry-run` 兜底 + 三方 hunk 检查 |
| T5 | LLM 删除 `.bak` 备份后写盘 | 落盘前强制 `.bak` 存在 |
| T6 | 编号字段（p 值、cell 数）被无声 silent edit | `audit/` 数字事实反推记录 |

---

## 快速开始

### 安装

```bash
git clone https://github.com/wuyutanhongyuxin-cell/paper_agent.git
cd paper_agent
pip install -e .
```

或者最小安装（只跑 audit，不编译）：

```bash
pip install -e . --no-deps
pip install jinja2
```

带开发依赖（跑测试）：

```bash
pip install -e ".[dev]"
pytest -v
```

### 30 秒上手

```bash
# 1. 初始化一个论文项目（你需要先有 <root>/src/paper.tex）
paper-agent init my-paper/ --lang zh --field linguistics

# 2. 跑一次审计
paper-agent audit my-paper/

# 3. 编译（pre-flight audit-gate 自动跑）
paper-agent compile my-paper/   # → my-paper/out/paper.pdf

# 4. LLM 写完一段后，你在真实终端复核 staged diff
paper-agent apply --paper-root my-paper/ --diff-id 20260525-093001-abc123
```

---

## 架构总览

```
┌────────────────────────────────────────────────────────────────┐
│ Layer 0  chinese-academic-paper-rigor skill (~150 行 wrapper) │
│          薄壳，把 prompt 翻译成 paper-agent CLI 调用            │
└────────────────────────────┬───────────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│ Layer 1  audit()         只读 API（rules/*.py 规则集）         │
│ Layer 2  advisory()      只读 + 写 advisory/<id>/               │
│ Layer 3  edit_gate()     写 paper.tex 的**唯一**路径            │
│                                                                 │
│          ↑ TTY 信任锚 / flock / sha256 三道闸                   │
└────────────────────────────────────────────────────────────────┘
```

### 两层 / 三 API 边界

| 层 | 调用者 | 副作用 | 信任要求 |
|----|--------|--------|---------|
| **Layer 0 skill** | LLM (chinese-academic-paper-rigor) | 无 | — |
| **Layer 1 audit** | LLM / human | `audit/<run_id>/<rule>.json` | 无 |
| **Layer 2 advisory** | LLM / human | `advisory/<diff_id>/{patch,note,sha}` | 无 |
| **Layer 3 edit_gate** | **仅 human 在真实 TTY** | 改写 `paper.tex` + `applied/<id>/` + `.bak` | TTY + flock + sha256 |

---

## CLI 参考

### `paper-agent init <paper-root>`

初始化一个 paper 项目，生成 `.latexmkrc` 和 `compile.ps1`。

```bash
paper-agent init my-paper/ \
    --lang zh \                  # zh / en (占位) / ja (占位)
    --field linguistics \        # linguistics / medicine / humanities / cs / sciences
    --paper-name paper           # 默认 "paper"，对应 <root>/src/<name>.tex
```

要求 `<root>/src/<paper-name>.tex` 已存在。

### `paper-agent audit <paper-root>`

跑只读审计，输出到 stdout 和 `audit/<run_id>/<rule>.json`。

```bash
paper-agent audit my-paper/ \
    --lang zh \
    --rules bib,punct,humanize \  # 逗号分隔，可只跑一部分
    --strict                       # ERROR-级 finding 退出 1（pre-compile hook 用）
```

退出码：
- `0`：无 ERROR（或非 strict 模式）
- `1`：strict 模式下有 ERROR

### `paper-agent compile <paper-root>`

调 `latexmk` 编译 PDF。内部经 `.latexmkrc` 的 `$pre_compile_hook` 自动跑 `paper-agent audit --strict`。

```bash
paper-agent compile my-paper/ --paper-name paper --strict
```

产物：`my-paper/out/paper.pdf`

### `paper-agent apply --paper-root <root> --diff-id <id>`

**唯一**改写 `paper.tex` 的子命令。**必须在真实终端运行**。

```bash
paper-agent apply --paper-root my-paper/ --diff-id 20260525-093001-abc123
```

流程：
1. 检查 `sys.stdin.isatty() and sys.stdout.isatty()`（Unix 兼用 `/dev/tty`，Windows 用 `CON`）
2. 取 `advisory/<diff-id>/{patch,note,sha}`
3. 拿排他 flock
4. 持锁内 sha256 复算 `paper.tex`，与 advisory 写入时的 sha256 比对（防 TOCTOU）
5. `patch --strict --dry-run` 验证 hunk 仍可应用
6. 打印 diff，提示 `[y/n/q]`，等真实键入
7. `y` → 备份 `.bak` → `patch --strict` 真应用 → 移到 `applied/<id>/`
8. `n` / `q` → 不动盘，archive 到 `applied/<id>/` 加 `REJECTED` 标记

退出码：
- `0`：应用成功 / 用户拒绝
- `1`：任一闸不通过

---

## Edit Gate 三层网关

### 为什么不用 JWT / HS256

最初设计有一层 JWT/keyring 想法："给真人发 token，LLM 没有 token 就不能写"。

**这个设计被删除了**，因为：

> 同进程的 LLM agent 和人类**用同一份代码、同一个 secret 文件**。密码学层面无法区分两者——LLM 可以读 keyring、可以重放 token、可以模拟键盘事件。任何"软件签名"在同进程里都是自欺欺人。

详见 spec §F.6（保留在 `E:\claude_ask\.knowledge\specs\` 设计冻结档）。

### 唯一可靠的信任锚 = 真实 TTY

```python
# core/edit_gate.py 真实实现简化版
def _verify_real_tty():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise NotATTYError("stdin/stdout not a TTY")
    # 同时直读 /dev/tty (Unix) / CON (Windows)，绕过任何 redirect / pipe
    tty_in  = open("/dev/tty" if os.name != "nt" else "CON", "rb")
    tty_out = open("/dev/tty" if os.name != "nt" else "CON", "wb")
    return tty_in, tty_out
```

LLM agent 跑在子进程或 pipe 里，三道闸全过不了：
1. `isatty()` 在 pipe 里返回 `False`
2. `/dev/tty` 直读绕过 stdin redirect
3. 即使 LLM 模拟键盘事件写到 stdin，flock + sha256 也兜底

### TOCTOU 防护

```
t0  LLM 拿到 sha256(paper.tex) = ABC, 写入 advisory/
t1  LLM 在等待人类批准时, 偷偷又改了 paper.tex (变成 sha = DEF)
t2  人类按 y
t3  edit_gate 在持锁内重新 sha256 → 得到 DEF ≠ ABC → 拒绝
```

锁的实现：Unix 用 `fcntl.flock(LOCK_EX | LOCK_NB)`，Windows 用 `msvcrt.locking(LK_NBLCK)`。详见 `core/edit_gate.py` 的 `_acquire_lock` / `_verify_sha256_under_lock`。

---

## 审计规则

### `bib_audit` （440 行迁入）

| 检查 | 严重度 |
|------|--------|
| `\cite{key}` 引用的 key 在 `.bib` 不存在 | ERROR |
| `.bib` 中的 entry 没有任何 `\cite` 引用（孤儿） | WARNING |
| GB/T 7714 风格：作者格式、文献类型标识符 | WARNING |
| biber `--tool --validate-datamodel` backend | ERROR（如 biber 可用） |
| LLM 伪造引用检测（标题/作者/年份三元组哈希） | ERROR |

### `punct_audit` P1–P7（347 行迁入）

| 编号 | 规则 |
|------|------|
| P1 | 中文段内半角逗号 `,` → 全角 `，`（保护千分位数字 `1,818,649`） |
| P2 | 中文段内半角句号 `.` → 全角 `。`（保护小数 `0.05`、缩写 `Dr.`） |
| P3 | 中文段半角括号 `(...)` → 全角 `（...）`（配对原子正则） |
| P4 | ARROW 残留 `→ ⇒ ← ⇐ ↔` |
| P5 | 引号配对 `"..." '...'` → 中文 `"…" '…'` |
| P6 | 中文段冒号 `:` → `：` |
| P7 | 中文段分号 `;` → `；` |
| P8–P9 | 0.2.0+ deferred（字间距 / 全角字母数字） |

### `humanize_check` R1–R7（293 行迁入）

| 编号 | 规则 |
|------|------|
| R1 | LLM 痕迹：`agent / LLM / AI / 大模型 / chatgpt / claude / gemini` |
| R2 | AI 高频中文词：`至关重要 / 综上所述 / 毋庸置疑 / 推动 / 赋能 / 破局 / 核心要义` 等 13 词 |
| R3 | AI 高频英文词：`comprehensive / robust / leverage / facilitate / paradigm` 等 |
| R4 | 模板套话：`本文 / 本研究 + 旨在 / 致力于` 等 |
| R5 | 致谢段伪造检测：不存在的匿名审稿人 / 项目方法论 / 资源 |
| R6 | 副词典型："此外" "首先...其次" 衔接词密度阈值 |
| R7 | 句长方差：AI 倾向写长度均匀的段落，方差 < 阈值告警 |

---

## 编译流水线

```
   src/paper.tex
        │
        ▼
┌───────────────────┐
│  .latexmkrc       │  $pre_compile_hook = paper-agent audit --strict
│  (Jinja2 渲染)    │  $pdf_mode = 5
│                   │  $xelatex = "xelatex %O %S"  ← %O 触发 -no-pdf 注入
└────────┬──────────┘
         │ latexmk 调度
         ▼
   ┌─────────────────────────────────────────────────┐
   │ pass 1   xelatex → paper.xdv (.aux 写入引用)    │
   │ pass 2   biber paper.bcf → paper.bbl            │
   │ pass 3   xelatex → 引用条目展开                  │
   │ pass 4   xelatex → 交叉引用稳定                  │
   │ pass 5   xdvipdfmx → paper.pdf                  │
   └─────────────────────────────────────────────────┘
                                │
                                ▼
                          out/paper.pdf
```

### 失败重试机制

latexmk 的 `fdb_latexmk` 缓存会记忆上次失败，导致下次 "Nothing to do"。如果上次 biber 失败：

```bash
latexmk -C   # 完全清理（jobname-scoped，安全）
paper-agent compile <root>
```

---

## 学科与语言支持

### 学科白名单（5 个）

| `--field` | 内置 fixture | 备注 |
|-----------|------------|------|
| `linguistics` | ✅ aphasia-zh-0.1.0 golden snapshot | 真实 paper 端到端验证 |
| `medicine`    | ✅ min_medicine_zh.tex/.bib | 单元测试 fixture |
| `humanities`  | ✅ min_humanities_zh.tex/.bib | 单元测试 fixture |
| `cs`          | ✅ min_cs_zh.tex/.bib | 单元测试 fixture |
| `sciences`    | ✅ min_sciences_zh.tex/.bib | 单元测试 fixture |

加新学科：见 [`docs/extending.md`](./docs/extending.md)。

### 语言支持

| `--lang` | 0.1.0 状态 | 规则集 |
|----------|-----------|--------|
| `zh` | ✅ 完整 | `audit/rules/zh.py`（punct P1-P7 + humanize R1-R7） |
| `en` | 🟡 占位 | `audit/rules/en.py`（`RULES = {}`，0.2.0+ 填充） |
| `ja` | 🟡 占位 | `audit/rules/ja.py`（`RULES = {}`，0.2.0+ 填充） |

加新语言：见 [`docs/extending.md`](./docs/extending.md)。

---

## 项目结构

```
paper-agent/
├── pyproject.toml            # 包元数据 + setuptools-scm 动态版本
├── README.md                 # 本文件
├── LICENSE                   # MIT
├── CHANGELOG.md              # 0.1.0 / 0.1.0.post1
├── docs/
│   ├── architecture.md       # spec §A-G 决策摘要
│   ├── cli.md                # CLI 详细参数
│   └── extending.md          # 加学科 / 语言 / 规则的指南
├── src/paper_agent/
│   ├── __init__.py
│   ├── _version.py           # setuptools-scm 自动生成（.gitignore）
│   ├── _util.py              # reconfigure_utf8 等 Windows quirk 兜底
│   ├── cli.py                # argparse 入口
│   ├── core/
│   │   ├── config.py         # PaperAgentConfig dataclass + 白名单
│   │   └── edit_gate.py      # Layer 1/2/3 三层 API
│   ├── audit/
│   │   ├── rule/
│   │   │   ├── bib_audit.py        # 440 行
│   │   │   ├── punct_audit.py      # 347 行
│   │   │   └── humanize_check.py   # 293 行
│   │   └── rules/
│   │       ├── zh.py               # 完整规则集
│   │       ├── en.py               # 占位
│   │       └── ja.py               # 占位
│   ├── compile/
│   │   ├── latexmkrc_gen.py        # Jinja2 渲染 .latexmkrc
│   │   ├── compile_ps1.py          # Jinja2 渲染 compile.ps1 + run_compile
│   │   └── templates/
│   │       ├── latexmkrc.j2        # 0.1.0.post1 修了 $biber 一行
│   │       └── compile.ps1.j2      # 一行 shim 调 paper-agent compile
│   └── golden_papers/
│       ├── index.json
│       └── aphasia-zh-0.1.0/       # 失语症 paper snapshot（regression fixture）
└── tests/
    ├── conftest.py
    ├── fixtures/                   # 5 学科 × min_*.tex/.bib + cp936 regression
    ├── test_bib_audit.py           # 3
    ├── test_cli.py                 # 8
    ├── test_compile.py             # 6
    ├── test_config.py              # 6
    ├── test_edit_gate.py           # 6 红队 T1-T6
    ├── test_edit_gate_advisory.py  # 3
    ├── test_edit_gate_platform.py  # 3（Unix/Windows TTY 抽象）
    ├── test_golden_papers.py       # 2
    ├── test_humanize_check.py      # 3
    ├── test_punct_audit.py         # 8
    ├── test_rules_registry.py      # 6
    └── integration/
        └── test_aphasia_e2e.py     # 5 真实 latexmk 编译
```

---

## 测试

```bash
# 全跑
pytest -v                              # 54 unit + 5 e2e = 59

# 只跑单元（快）
pytest tests/ --ignore=tests/integration -v

# 只跑 e2e（需 latexmk + biber + xelatex 在 PATH）
pytest tests/integration -v

# 跑某一类
pytest tests/test_edit_gate.py -v      # 红队 T1-T6
pytest tests/test_punct_audit.py -v    # P1-P7
```

### 覆盖率

```bash
pytest --cov=paper_agent --cov-report=html
# → htmlcov/index.html
```

### CI 期望

| 平台 | 单元 | E2E |
|------|------|-----|
| Linux + TeX Live | ✅ 54 pass | ✅ 5 pass |
| macOS + MacTeX | ✅ 54 pass | ✅ 5 pass |
| Windows + MiKTeX + Strawberry Perl | ✅ 54 pass | ✅ 5 pass |
| Windows + MiKTeX **without** Perl | ✅ 54 pass | ⚠️ 5 skip（latexmk 是 Perl 脚本） |

---

## 外部依赖

### Python

- Python ≥ 3.11
- jinja2 ≥ 3

### LaTeX 工具链

| 工具 | 最低版本 | 推荐 | 作用 |
|------|---------|------|------|
| `latexmk` | 4.70 | **4.88+** | manpage 文档化 `%O` 契约从 4.70 起；4.88 是 stable 长期版本 |
| `xelatex` | TeXLive 2020+ | TeXLive 2024+ / MiKTeX 25.x | UTF-8 + 中日韩字体 |
| `biber` | 2.16 | 2.21 | bibliography 后端 |
| `xdvipdfmx` | TeXLive 2020+ | — | `.xdv → .pdf` |

### 可选

| 工具 | 作用 |
|------|------|
| `chktex` | post-flight LaTeX lint（informational, 不阻断） |
| `bibtool` | `bib_audit` 的 todo-pattern backend |

### Windows 特有

| 工具 | 作用 |
|------|------|
| **MiKTeX 25.12+** | 提供 latexmk / xelatex / biber 包，**但不自带 Perl** |
| **Strawberry Perl 5.42+ (portable)** | latexmk 是 Perl 脚本，无 Perl 编译会立刻报 "could not find script engine 'perl'" |

---

## 安装故障排查（Windows）

### 症状 1：`where latexmk` 返回 not found，但 MiKTeX 已装

MiKTeX 的 `bin` 不在 User PATH 的 session 中。检查：

```powershell
[Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Select-String 'miktex'
```

如果没有，重启 PowerShell（或登出登入）让 PATH 生效。

### 症状 2：`latexmk` 报 "MiKTeX could not find the script engine 'perl'"

需要 Strawberry Perl Portable：

```powershell
# 1. 下载（~290 MB）
Invoke-WebRequest -Uri "https://github.com/StrawberryPerl/Perl-Dist-Strawberry/releases/download/SP_54221_64bit/strawberry-perl-5.42.2.1-64bit-portable.zip" `
                  -OutFile "$env:USERPROFILE\Downloads\strawberry-perl-portable.zip"

# 2. 解压到无空格 ASCII 路径
Expand-Archive "$env:USERPROFILE\Downloads\strawberry-perl-portable.zip" -DestinationPath "E:\strawberry-portable"

# 3. 加入 User PATH（备份当前 PATH）
$old = [Environment]::GetEnvironmentVariable('Path', 'User')
$old | Out-File "$env:USERPROFILE\Downloads\user-path-before-strawberry.txt"
[Environment]::SetEnvironmentVariable('Path',
    "E:\strawberry-portable\perl\site\bin;E:\strawberry-portable\perl\bin;E:\strawberry-portable\c\bin;$old",
    'User')

# 4. 验证（重启 PowerShell 后）
perl -v        # → v5.42.2
latexmk --version    # → 4.88
biber --version      # → 2.21
xelatex --version    # → 4.16
```

### 症状 3：`paper-agent compile` 报 biber "Option output-directory requires an argument"

这是 **0.1.0 的 bug，0.1.0.post1 已修**。如果你已经 `paper-agent init` 过的旧项目：

```bash
# 手动修 <paper-root>/.latexmkrc 删掉这一行：
# $biber = "biber --output-directory=%O %O %S";

# 或重新 init 一遍：
paper-agent init <paper-root> --lang zh --field linguistics
```

或者升级到 0.1.0.post1 后重新生成。

---

## 路线图

### 0.1.x（已发布）

- ✅ 0.1.0 — CLI 4 子命令 / 3 audit 规则 / Edit Gate 三层 / latexmk 替代 / 5 学科 fixture / 失语症 golden
- ✅ 0.1.0.post1 — 修 `latexmkrc.j2` 的 `$biber` 一行（biber 必失败 bug）

### 0.1.1（计划中）

- 🔵 4 条新 audit 规则：`fig_audit` / `stat_audit` / `related_work_audit` / `sample_audit`
- 🔵 `bib_audit` 接入 biber `--tool --validate-datamodel` backend
- 🔵 `humanize_check` R8–R10：段落语义重复度 / 情感色彩异常 / 自引用循环

### 0.2.0+（设想）

- 🟣 `--lang en` 完整规则集
- 🟣 `--lang ja` 完整规则集
- 🟣 `paper-agent diff <a> <b>`：跨版本审计 diff
- 🟣 `paper-agent gallery`：把 advisory 历史可视化成时间线

### 长期通用化（与 chinese-academic-paper-rigor 协同）

- 🔴 多领域多语言多论文 — 工具必须 CLI 参数化、不 hardcode 学科名词、跨学科 schema 可消费
- 🔴 至少 1 个非失语症 fixture 验证（已有 5 个 min_*.tex，下一步加非语言学的 e2e）

---

## 设计哲学

### 1. 不破不立

现成项目能 `pip install` / `git clone` 就直接用，不复写：
- latexmk 替代手写 4-pass（130 行 → 30 行）
- python-docx / jinja2 / patch / biber 全用现成

### 2. 信任不靠密码学，靠 I/O 路径

LLM agent 和人类在同进程里，密码学层面无法区分。唯一可靠的信任锚是**人类只能通过 TTY 与你交互，agent 只能通过 pipe**。

### 3. 审计痕迹优于事后调查

任何写盘动作都留下 4 份痕迹：
- `audit/<run_id>/<rule>.json` — 当时的 finding 快照
- `advisory/<diff_id>/{patch,note,sha}` — LLM 提议
- `applied/<diff_id>/` — 人类批准的最终 patch
- `<file>.bak` — 写盘前的备份

任何一份缺失，事后都能精确重现写盘瞬间的全状态。

### 4. 长期通用化优于短期定制

paper-agent 不依赖任何特定论文 / 学科 / 语言的 hardcode。所有学科特异规则归 `projects/<name>/rules/`（用户侧），通用规则归 `paper_agent/audit/rules/<lang>.py`（包内）。

---

## 链接

- **仓库**: https://github.com/wuyutanhongyuxin-cell/paper_agent
- **changelog**: [CHANGELOG.md](./CHANGELOG.md)
- **架构文档**: [docs/architecture.md](./docs/architecture.md)
- **CLI 详细参考**: [docs/cli.md](./docs/cli.md)
- **扩展指南**: [docs/extending.md](./docs/extending.md)

---

## License

MIT — 见 [LICENSE](./LICENSE)。

---

> **致谢**：感谢失语症词汇筛选课题组提供真实论文作为 golden fixture，让 paper-agent 0.1.0 的 e2e 验证不是"空跑"。
