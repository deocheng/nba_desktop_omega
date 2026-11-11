#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock 端到端测试 (不依赖真实权重): 用本地 stdlib HTTP server 模拟 PrismML llama-server,
验证 bonsai_poc.py 的完整管线正确性:
  1) 图像读取 + base64 编码
  2) OpenAI 视觉格式 payload 构造 (image_url + text)
  3) POST /v1/chat/completions 请求发送
  4) LIVE/DEAD 解析 (含带废话的鲁棒性)
  5) --expect 准确率计算
  6) JSON 报告写出
并验证 run_bonsai_poc.sh 的健康检查: server 不可达时应报错退出 (非零)。

用法: python3 test_poc_mock.py
"""
import base64
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

BONSAI_DIR = os.path.dirname(os.path.abspath(__file__))
# 三张代表帧字节长度 -> ground truth (mock 借此"识别"是哪张图, 自包含)
EXPECT_BY_SIZE = {344388: "DEAD", 297740: "LIVE", 361115: "LIVE"}


class MockHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.endswith("/v1/chat/completions"):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            img_b64 = None
            for part in req["messages"][0]["content"]:
                if part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    assert url.startswith("data:image/jpeg;base64,"), "image_url 格式错"
                    img_b64 = url.split(",", 1)[1]
            raw = base64.b64decode(img_b64)
            assert raw[:2] == b"\xff\xd8", "解码后不是合法 JPEG (缺 ffd8 头)"
            size = len(raw)
            word = EXPECT_BY_SIZE.get(size, "UNKNOWN")
            # 故意带废话, 验证解析鲁棒性
            self._send(200, {"choices": [{"message": {"content": f"Looking closely, this frame is {word}-ball."}}]})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18080), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SERVER = "http://127.0.0.1:18080"
    frames = [os.path.join(BONSAI_DIR, "poc_frames", f) for f in
              ["cand_1244_DEAD.jpg", "cand_932_LIVE.jpg", "possA_full_LIVE.jpg"]]
    out = os.path.join(tempfile.gettempdir(), "poc_verdict_test.json")

    # 1) 端到端: 三帧都应为完美判定 -> 3/3
    r = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "bonsai_poc.py"),
                        "--server", SERVER, "--out", out,
                        "--expect", "DEAD,LIVE,LIVE"] + frames,
                       capture_output=True, text=True)
    print("=== bonsai_poc.py (expect DEAD LIVE LIVE) ===")
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr)
        sys.exit(1)
    assert "证伪准确率: 3/3" in r.stdout and "(100%)" in r.stdout, "期望 3/3 全中"
    rep = json.load(open(out))
    assert len(rep) == 3 and all(x["correct"] for x in rep), "报告应全对"
    assert all(x["verdict"] == x["expected"] for x in rep)
    print("PASS 1: 图像编码/请求/解析/准确率/报告 全对 (3/3)")

    # 2) 鲁棒性: 故意乱序 expect -> 应标记 0/3 (验证对比逻辑)
    r2 = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "bonsai_poc.py"),
                         "--server", SERVER, "--expect", "LIVE,DEAD,DEAD"] + frames,
                        capture_output=True, text=True)
    assert "证伪准确率: 0/3" in r2.stdout and "(0%)" in r2.stdout, "乱序应 0/3"
    print("PASS 2: 错判标记正确 (0/3)")

    # 3) runner 健康检查: 不可达端口应报错退出
    bad = subprocess.run(["bash", os.path.join(BONSAI_DIR, "run_bonsai_poc.sh")],
                         env={**os.environ, "BONSAI_SERVER": "http://127.0.0.1:19999"},
                         capture_output=True, text=True)
    assert bad.returncode != 0 and "未运行" in bad.stdout, "runner 应在 server 不可达时报错"
    print("PASS 3: run_bonsai_poc.sh 健康检查 (server 不可达正确报错退出)")

    srv.shutdown()
    print("\nALL MOCK TESTS PASSED")


if __name__ == "__main__":
    main()
