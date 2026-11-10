#!/usr/bin/env python3
"""detach.py — 真正的 daemon 脱离启动器（macOS 无 setsid 命令）。

为什么需要
--------
WorkBuddy 的 Bash 工具在一次调用结束时会把**整个进程树**回收掉，
所以 `nohup cmd &` + `disown` 起的服务会在命令返回的瞬间消失：
端口随即空出来，下一次启动就会撞上 "address already in use" 或
反过来重复起实例。这正是 2026-11-10 13:14 那次 [Errno 48] 的成因。

做法
----
经典双 fork + setsid：
  1. 第一次 fork，父进程立刻退出（调用方马上返回）；
  2. 子进程 setsid() 脱离当前会话/进程组，成为新组长；
  3. 第二次 fork，退出中间进程，让最终孙进程被 init 收养；
  4. execv 目标程序，stdin 接到 /dev/null，stdout/stderr 接日志。

这样出来的进程与调用方的会话、进程组、终端全部无关，
调用方退出、WorkBuddy 回收进程树都不会带走它。

用法
----
    python3 detach.py <logfile> <cmd> [args...]
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write("usage: detach.py <logfile> <cmd> [args...]\n")
        return 2

    logfile = sys.argv[1]
    cmd = sys.argv[2:]

    # --- 第一次 fork：父进程立刻退出，调用方马上返回 ---
    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)   # 回收中间子进程，避免僵尸
        return 0

    # --- 子进程：脱离会话 ---
    try:
        os.setsid()
    except OSError:
        pass

    # --- 第二次 fork：最终进程交给 init 收养 ---
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # --- 重定向标准流 ---
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)

    logfd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(logfd)

    # --- 换掉工作目录并执行目标 ---
    os.chdir("/")
    os.execv(cmd[0], cmd)

    return 1  # 只有 execv 失败才会走到这


if __name__ == "__main__":
    sys.exit(main())
