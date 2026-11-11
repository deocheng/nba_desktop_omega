#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock 端到端测试 (不依赖真实模型): 本地 HTTP server 模拟 llama-server /v1/chat/completions,
验证 local_decisions_client.py 的多帧请求构造 + logprobs 解析 + 置信度路由 + 准确率 + 报告。

mock 行为: 按帧字节长度判 clip 类别(沿用三代表帧尺寸), 返回 OpenAI 风格 logprobs 响应,
首 token top_logprobs 含 LIVE/DEAD 概率 -> 验证客户端能从中取出真实置信度并路由。

用法: python3 test_local_decisions_mock.py
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
EXPECT_BY_SIZE = {344388: "DEAD", 297740: "LIVE", 361115: "LIVE"}


class MockHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.endswith("/v1/chat/completions"):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            imgs = [p for p in req["messages"][0]["content"] if p.get("type") == "image_url"]
            sizes = []
            for im in imgs:
                url = im["image_url"]["url"]
                assert url.startswith("data:image/jpeg;base64,"), "image_url 格式错"
                raw = base64.b64decode(url.split(",", 1)[1])
                assert raw[:2] == b"\xff\xd8", "解码后不是合法 JPEG"
                sizes.append(len(raw))
            is_dead = any(EXPECT_BY_SIZE.get(s) == "DEAD" for s in sizes)
            # 首 token top_logprobs: 给 LIVE/DEAD 真实概率(模拟 logprobs 机制)
            if is_dead:
                p_live, p_dead = 0.05, 0.93
            else:
                p_live, p_dead = 0.94, 0.04
            # logprob 形式(客户端会 exp 还原); 也带 prob 字段兼容
            import math
            resp = {
                "model": "local",
                "choices": [{
                    "message": {"content": "DEAD" if is_dead else "LIVE"},
                    "logprobs": {"content": [{
                        "token": "DEAD" if is_dead else "LIVE",
                        "logprob": math.log(p_dead if is_dead else p_live),
                        "top_logprobs": [
                            {"token": "LIVE", "logprob": math.log(p_live), "prob": p_live},
                            {"token": "DEAD", "logprob": math.log(p_dead), "prob": p_dead},
                        ],
                    }]},
                }],
            }
            self._send(200, resp)
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18077), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SERVER = "http://127.0.0.1:18077"
    frames = [os.path.join(BONSAI_DIR, "poc_frames", f) for f in
              ["cand_1244_DEAD.jpg", "cand_932_LIVE.jpg", "possA_full_LIVE.jpg"]]
    out = os.path.join(tempfile.gettempdir(), "local_decisions_verdict_test.json")

    # 1) 单帧对表: mock 给的真实概率应被取出 -> 3/3 + 高置信
    r = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "local_decisions_client.py"),
                        "--server", SERVER, "--per-image",
                        "--expect", "DEAD,LIVE,LIVE", "--out", out] + frames,
                       capture_output=True, text=True)
    print("=== local_decisions_client.py 单帧(per-image, expect DEAD LIVE LIVE) ===")
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr)
        sys.exit(1)
    assert "证伪准确率: 3/3" in r.stdout and "(100%)" in r.stdout, "期望 3/3 全中"
    rep = json.load(open(out))
    assert len(rep) == 3 and all(x["correct"] for x in rep), "报告应全对"
    # 验证置信度真的从 logprobs 取出(非 None)
    assert all(x["parsed"].get("confidence") is not None for x in rep), "应取到 logprobs 置信度"
    print("PASS 1: 多帧请求构造/logprobs 解析/置信度路由/准确率/报告 全对 (3/3, 单帧)")

    # 2) 低置信路由: 临时用极高阈值, 全部应转 HUMAN_REVIEW
    r2 = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "local_decisions_client.py"),
                         "--server", SERVER, "--per-image",
                         "--confidence-threshold", "0.999",
                         "--expect", "DEAD,LIVE,LIVE"] + frames,
                        capture_output=True, text=True)
    assert "-> HUMAN_REVIEW" in r2.stdout, "高阈值下应全部转人工"
    print("PASS 2: 低置信路由(阈值 0.999) -> HUMAN_REVIEW 生效")

    # 3) 多帧单请求: 三帧一包 -> 含 DEAD 帧应判 DEAD
    r3 = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "local_decisions_client.py"),
                         "--server", SERVER, "--expect", "DEAD"] + frames,
                        capture_output=True, text=True)
    assert "-> DEAD" in r3.stdout, "多帧(含 DEAD 帧)应判 DEAD"
    print("PASS 3: 多帧单请求构造正确 -> DEAD (破单帧歧义路径)")

    srv.shutdown()
    print("\nALL LOCAL DECISIONS MOCK TESTS PASSED")


if __name__ == "__main__":
    main()
