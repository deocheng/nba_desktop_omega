#!/usr/env python3
# -*- coding: utf-8 -*-
"""
本地服务：让 calendar.html 能在浏览器里直接播 /Volumes/12T/NBA 下的录像。
- GET /            -> 服务 calendar.html (项目目录)
- GET /video/<p>  -> 服务 /Volumes/12T/NBA/<p>，显式支持 Range 请求(拖动进度条必需)
- 仅绑定 127.0.0.1，禁止目录穿越。

用法:
  .venv/bin/python serve_calendar.py           # 默认 8765
  .venv/bin/python serve_calendar.py 9000    # 自定义端口
然后浏览器打开 http://localhost:8765/
"""
import sys, os, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

VIDEO_ROOT = "/Volumes/12T/NBA"
HERE = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(HERE, "calendar.html")
CHUNK = 64 * 1024

def guess_type(p):
    t, _ = mimetypes.guess_type(p)
    return t or "application/octet-stream"

class Handler(BaseHTTPRequestHandler):
    def _safe(self, rel):
        # 规范化并禁止穿越出 VIDEO_ROOT
        fp = os.path.normpath(os.path.join(VIDEO_ROOT, rel))
        if fp != VIDEO_ROOT and not fp.startswith(VIDEO_ROOT + os.sep):
            return None
        if not os.path.isfile(fp):
            return None
        return fp

    def do_GET(self):
        p = unquote(urlparse(self.path).path)
        if p in ("/", "/index.html", "/calendar.html"):
            try:
                data = open(HTML_FILE, "rb").read()
            except OSError:
                self.send_error(404, "calendar.html 未生成，请先运行 scan_videos.py")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if p.startswith("/video/"):
            fp = self._safe(p[7:])
            if fp is None:
                self.send_error(404)
                return
            self._serve_range(fp)
            return
        self.send_error(404)

    def _serve_range(self, fp):
        size = os.path.getsize(fp)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.lower().startswith("bytes="):
            spec = rng[6:].split(",")[0].strip()
            if "-" in spec:
                s, e = spec.split("-", 1)
                start = int(s) if s else 0
                end = int(e) if e else size - 1
                if end >= size:
                    end = size - 1
        if start < 0 or start > end or start >= size:
            self.send_error(416, "Range Not Satisfiable")
            return
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", guess_type(fp))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(fp, "rb") as f:
            f.seek(start)
            remaining = length
            try:
                while remaining > 0:
                    buf = f.read(min(CHUNK, remaining))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    remaining -= len(buf)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 客户端中断(拖动)属正常

    def log_message(self, *a):
        pass

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    if not os.path.exists(HTML_FILE):
        sys.exit("找不到 calendar.html，请先运行 scan_videos.py 生成。")
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"录像日历服务已启动: http://localhost:{port}/")
    print(f"录像根目录: {VIDEO_ROOT}  (Ctrl+C 停止)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()

if __name__ == "__main__":
    main()
