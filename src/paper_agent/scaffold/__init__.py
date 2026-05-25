"""Scaffold module: bootstrap an empty paper project skeleton.

`paper-agent new <paper_root>` 调本模块的 write_paper_skeleton() 生成
src/paper.tex + src/references.bib 占位骨架（jinja2 模板），随后 CLI 接力调
compile.{latexmkrc_gen,compile_ps1} 把 .latexmkrc + compile.ps1 也生成出来，
形成"一键开新 paper 项目"工作流。

Why:
  0.1.0/0.1.0.post2 的 paper-agent init 只生成构建链 (.latexmkrc / compile.ps1)，
  论文源 (paper.tex / references.bib) 仍要用户手抄；这条体验缺口让"通用化论文
  agent"承诺缺一块兜底，详见 [[feedback_paper_agent_long_term_generality]]。
"""
from .new_project import write_paper_skeleton

__all__ = ["write_paper_skeleton"]
