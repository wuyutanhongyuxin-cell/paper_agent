"""平台抽象单测：_acquire_exclusive_lock + _is_real_tty。"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def test_acquire_exclusive_lock_works(tmp_path):
    """同进程在同一打开 fd 上锁两次也应 ok（reentrant 不强制；锁释放跟随 fd close）。"""
    from paper_agent.core.edit_gate import _acquire_exclusive_lock

    p = tmp_path / "x.tex"
    p.write_text("hello", encoding="utf-8")
    with open(p, "r+b") as f:
        _acquire_exclusive_lock(f)
        # 锁释放跟随 with 退出


def test_concurrent_lock_blocks(tmp_path):
    """另一 process 锁住时，本进程 lock 应抛或非阻塞失败。Windows: msvcrt.locking LK_NBLCK。"""
    from paper_agent.core.edit_gate import _acquire_exclusive_lock

    p = tmp_path / "y.tex"
    p.write_text("data", encoding="utf-8")

    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import time, sys\n"
         f"from paper_agent.core.edit_gate import _acquire_exclusive_lock\n"
         f"f = open(r'{p}', 'r+b'); _acquire_exclusive_lock(f); time.sleep(3)"],
        env=env,
    )
    time.sleep(1.0)
    try:
        with open(p, "r+b") as f:
            with pytest.raises(BlockingIOError):
                _acquire_exclusive_lock(f)
    finally:
        holder.wait(timeout=5)


def test_is_real_tty_default_in_pytest_is_false():
    """pytest 跑测试时 stdin/stdout 是 pipe，不是真 TTY。"""
    from paper_agent.core.edit_gate import _is_real_tty
    assert _is_real_tty() is False
