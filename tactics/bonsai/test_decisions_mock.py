#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock 端到端测试 (不依赖真实 key): 用本地 stdlib HTTP server 模拟 OpenAI /v1/decisions,
验证 decisions_client.py 完整管线:
  1) 图像读取 + base64 编码 (多帧内联)
  2) Decisions 请求构造 (input=user messages w/ images + questions[type/instructions/choices])
  3) POST /v1/decisions 请求发送
  4) choice/predicate 答案解析 + 路由(低 confidence -> HUMAN_REVIEW)
  5) --expect 准确率计算 + JSON 报告写出
并验证护栏: 指向官方端点且无 key 应报错退出(不误扣费).

用法: python3 test_decisions_mock.py
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

    def do_POST(self):
        if self.path.endswith("/v1/decisions"):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            # 找 input 里所有图像, 用总字节判定 clip 类别 (单帧按帧, 多帧含 DEAD 帧即 DEAD)
            imgs = [p for p in req["input"][0]["content"] if p.get("type") == "input_image"]
            sizes = []
            for im in imgs:
                url = im["image_url"]["url"]
                assert url.startswith("data:image/jpeg;base64,"), "image_url 格式错"
                raw = base64.b64decode(url.split(",", 1)[1])
                assert raw[:2] == b"\xff\xd8", "解码后不是合法 JPEG (缺 ffd8 头)"
                sizes.append(len(raw))
            is_dead = any(EXPECT_BY_SIZE.get(s) == "DEAD" for s in sizes)
            q = req["questions"][0]
            qname = q["name"]
            qtype = q["type"]
            if qtype == "choice":
                ans = {"type": "choice", "name": qname,
                       "choice": "DEAD" if is_dead else "LIVE",
                       "confidence": 0.97 if is_dead else 0.95,
                       "probabilities": [
                           {"probability": 0.03 if is_dead else 0.95, "value": "LIVE"},
                           {"probability": 0.97 if is_dead else 0.05, "value": "DEAD"},
                       ]}
            elif qtype == "predicate":
                ans = {"type": "predicate", "name": qname,
                       "probability": 0.95 if is_dead else 0.05}
            else:
                ans = {"type": "refusal", "name": qname}
            self._send(200, {"model": "gpt-6-luna", "answers": [ans],
                             "usage": {"input_tokens": 1234, "output_tokens": 0,
                                       "total_tokens": 1234}})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18099), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SERVER = "http://127.0.0.1:18099/v1/decisions"  # 客户端把 base-url 当完整端点 URL
    frames = [os.path.join(BONSAI_DIR, "poc_frames", f) for f in
              ["cand_1244_DEAD.jpg", "cand_932_LIVE.jpg", "possA_full_LIVE.jpg"]]
    out = os.path.join(tempfile.gettempdir(), "decisions_verdict_test.json")

    # 1) choice 单帧对表: 三帧都应完美判定 -> 3/3
    r = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "decisions_client.py"),
                        "--base-url", SERVER, "--api-key", "dummy",
                        "--mode", "choice", "--per-image",
                        "--expect", "DEAD,LIVE,LIVE", "--out", out] + frames,
                       capture_output=True, text=True)
    print("=== decisions_client.py choice/per-image (expect DEAD LIVE LIVE) ===")
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr)
        sys.exit(1)
    assert "证伪准确率: 3/3" in r.stdout and "(100%)" in r.stdout, "期望 3/3 全中"
    rep = json.load(open(out))
    assert len(rep) == 3 and all(x["correct"] for x in rep), "报告应全对"
    assert all(x["verdict"] == x["expected"] for x in rep)
    print("PASS 1: 图像编码/请求/解析/路由/准确率/报告 全对 (3/3, choice)")

    # 2) predicate 单帧对表: 同样 3/3
    r2 = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "decisions_client.py"),
                         "--base-url", SERVER, "--api-key", "dummy",
                         "--mode", "predicate", "--per-image",
                         "--expect", "DEAD,LIVE,LIVE"] + frames,
                        capture_output=True, text=True)
    assert "证伪准确率: 3/3" in r2.stdout and "(100%)" in r2.stdout, "predicate 也应 3/3"
    print("PASS 2: predicate 模式同样 3/3 全中")

    # 3) 多帧单请求: 把三帧作为一个 clip 喂进去 -> mock 含 DEAD 帧即判 DEAD
    r3 = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "decisions_client.py"),
                         "--base-url", SERVER, "--api-key", "dummy",
                         "--mode", "choice",
                         "--expect", "DEAD"] + frames,
                        capture_output=True, text=True)
    assert "-> DEAD" in r3.stdout, "多帧(含 DEAD 帧)应判 DEAD"
    print("PASS 3: 多帧单请求(破单帧歧义路径)构造正确 -> DEAD")

    # 4) 护栏: 指向官方端点且无 key 应报错退出
    bad = subprocess.run([sys.executable, os.path.join(BONSAI_DIR, "decisions_client.py"),
                          "--mode", "choice", "--per-image"] + frames,
                         capture_output=True, text=True)
    assert bad.returncode != 0 and "OPENAI_API_KEY 未设置" in bad.stderr, "无 key 不应发起真实请求"
    print("PASS 4: 护栏生效(官方端点无 key 拒绝扣费)")

    srv.shutdown()
    print("\nALL DECISIONS MOCK TESTS PASSED")


if __name__ == "__main__":
    main()
