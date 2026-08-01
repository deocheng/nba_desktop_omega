#!/usr/bin/env python3
"""真·脱离会话启动器：双 fork + setsid，把目标命令过继给 launchd(PID 1)。

用途：从 agent 工具 shell / 终端启动长跑任务时，避免会话结束把进程组整树带走
（nohup 只挡 SIGHUP，挡不住会话级 SIGTERM/清理）。

用法:
    python3 detach_launch.py <logfile> <cmd> [args...]
例:
    python3 detach_launch.py /Volumes/12T/NBA/resume_launcher.log bash resume_shooting_shotchart.sh
"""
import os
import sys

def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: detach_launch.py <logfile> <cmd> [args...]")
    logfile, cmd = sys.argv[1], sys.argv[2:]
    cwd = os.getcwd()

    # 第一次 fork：父进程立即返回（工具 shell 拿到退出码 0）
    if os.fork() > 0:
        return
    # 新会话：脱离原会话/进程组/控制终端
    os.setsid()
    # 第二次 fork：会话首进程退出 → 孙进程被 launchd 收养，永不再获得控制终端
    if os.fork() > 0:
        os._exit(0)

    os.chdir(cwd)
    fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.execvp(cmd[0], cmd)

if __name__ == "__main__":
    main()
