#!/usr/bin/env python3
"""并行分片下载 RelateAnything 权重（绕代理 + 多路 range）

背景：本机出站代理在 HF 的 /resolve/ 下载端点上返 502/000，必须直连；
直连单连接仅 ~48KB/s，8 路并行可叠到 ~380KB/s。

输出目录布局按 from_checkpoint 的约定：
    <dest>/model.pth            主权重
    <dest>/text_student.pt      谓词文本编码器（须与 model.pth 同级）
    <dest>/calibration.json     分数标定
    <dest>/predicate_embeddings.npz
    <dest>/tokenizer.json, tokenizer_config.json
"""
from __future__ import annotations

# --- nba-paths bootstrap (auto, idempotent) ---
import sys as _nba_sys
from pathlib import Path as _nba_Path

_nba_sys.path.insert(0, str(_nba_Path(__file__).resolve().parents[2]))
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from common.nba_paths import workspace_file

REPO = "maelic/relsgg-vits16plus"
FILES = [
    ("model.pth", 257_112_000),
    ("text_student.pt", 44_968_057),
    ("predicate_embeddings.npz", 18_150_000),
    ("tokenizer.json", 3_640_000),
    ("tokenizer_config.json", 1_000),
    ("calibration.json", 1_000),
]
CHUNK = 4 * 1024 * 1024
WORKERS = 8

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_lock = threading.Lock()
_done = [0]


def url_for(name: str) -> str:
    return f"https://huggingface.co/{REPO}/resolve/main/{name}"


def head_size(name: str) -> int:
    req = urllib.request.Request(url_for(name), method="HEAD")
    with _opener.open(req, timeout=30) as r:
        return int(r.headers.get("Content-Length", 0))


def fetch_range(name: str, start: int, end: int, path: str, attempt: int = 0):
    """下载 [start, end] 写入 path 的对应偏移。"""
    hdr = {"Range": f"bytes={start}-{end}", "Connection": "close",
           "User-Agent": "curl/8"}
    req = urllib.request.Request(url_for(name), headers=hdr)
    try:
        with _opener.open(req, timeout=120) as r:
            data = r.read()
        if len(data) != end - start + 1:
            raise IOError(f"short read {len(data)} != {end-start+1}")
        with open(path, "r+b") as f:
            f.seek(start)
            f.write(data)
        with _lock:
            _done[0] += len(data)
    except Exception as e:
        if attempt >= 4:
            raise
        time.sleep(1.5 * (attempt + 1))
        fetch_range(name, start, end, path, attempt + 1)


def download(name: str, dest: str, size: int) -> None:
    path = os.path.join(dest, name)
    if os.path.exists(path) and os.path.getsize(path) == size:
        print(f"  [skip] {name} 已完整 ({size/1e6:.1f} MB)", flush=True)
        return
    jobs = [(s, min(s + CHUNK - 1, size - 1)) for s in range(0, size, CHUNK)]
    t0 = time.perf_counter()
    with open(path, "wb") as f:                       # 预分配
        f.truncate(size)
    before = _done[0]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(lambda j: fetch_range(name, j[0], j[1], path), jobs))
    got = _done[0] - before
    dt = time.perf_counter() - t0
    ok = os.path.getsize(path) == size
    print(f"  [{'ok' if ok else 'BAD'}] {name} {size/1e6:.1f} MB "
          f"in {dt:.0f}s ({got/dt/1024:.0f} KB/s, {len(jobs)} 分片)", flush=True)
    if not ok:
        raise SystemExit(f"{name} 大小不符: {os.path.getsize(path)} != {size}")


def main() -> int:
    dest = sys.argv[1] if len(sys.argv) > 1 else \
        str(workspace_file("action_work/models/relsgg-vits16plus"))
    os.makedirs(dest, exist_ok=True)
    print(f"[dest] {dest}")
    total0 = time.perf_counter()
    for name, declared in FILES:
        size = head_size(name)
        if size <= 0:
            size = declared
        download(name, dest, size)
    print(f"[done] 全部完成，用时 {time.perf_counter()-total0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
