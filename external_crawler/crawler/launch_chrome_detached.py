#!/usr/bin/env python3
"""Detached launcher for macOS (survives WorkBuddy background-task killpg recycling).

Pattern (double-fork + setsid):
  1. Parent calls os.setsid() -> own session/PG (this is the tracked background task).
  2. Parent forks; parent exits immediately (task "completes").
  3. Child calls os.setsid() again -> brand-new session/PG, then execv(TARGET).

Result: the target (e.g. Chrome with --remote-debugging-port=9223) lives in a
process group that is NOT the background task's group, so the platform's killpg
on task completion / recycle only hits the (already exited) parent, never Chrome.

Usage (Bash tool, run_in_background):
  env -u HTTP_PROXY -u HTTPS_PROXY python3 launch_chrome_detached.py /bin/bash launch_chrome_cdp.sh
"""
import os
import sys

if len(sys.argv) < 2:
    print("usage: launch_chrome_detached.py <cmd> [args...]", file=sys.stderr)
    sys.exit(1)

# 1) Parent detaches into its own session (this PID is what the task tracker sees).
os.setsid()

# 2) Fork; parent exits so the background task "completes" while child survives.
pid = os.fork()
if pid > 0:
    os._exit(0)

# 3) Child becomes its own session/process-group, then exec the target.
os.setsid()
os.execv(sys.argv[1], sys.argv[1:])
