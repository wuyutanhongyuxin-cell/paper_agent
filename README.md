# paper-agent

学术论文审计 + Edit Gate 流水线（保证 LLM 0-write `paper.tex`）。

## 安装

```bash
pip install -e .
```

## 用法

```bash
paper-agent init <paper-root> --lang zh --field linguistics
paper-agent audit <paper-root> --rules bib,punct,humanize
paper-agent compile <paper-root>
paper-agent apply --diff-id <id>   # 必在真实终端
```

详见 `docs/cli.md`。

## License

MIT
