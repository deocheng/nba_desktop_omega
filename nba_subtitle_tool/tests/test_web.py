"""Web UI run->status->download 流程测试（使用 Flask test_client，无需网络）。

用假模型路径验证：
  - POST /api/run 返回 job_id 并启动子进程
  - GET /api/status 能从 running 收敛到 failed（并捕获日志）
  - 成功路径下 GET /api/file/<job_id>/<ext> 能返回文件

真正的 ASR 成功路径依赖本地 Whisper 模型，需手动下载后实跑验证。
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web import JOBS, OUTPUT, WORK, app


def _make_fake_model(tmpdir):
    os.makedirs(tmpdir, exist_ok=True)
    with open(os.path.join(tmpdir, "model.bin"), "w") as f:
        f.write("")  # 空文件 -> faster-whisper 加载即报错，确定性失败


def test_run_status_failed_flow():
    client = app.test_client()
    fake = "/tmp/fakewhisper_webtest"
    _make_fake_model(fake)
    video = os.path.join(WORK, "demo_clip.mp4")
    if not os.path.exists(video):
        # 退化为任意存在的视频；失败路径与视频内容无关
        video = os.path.join(os.path.dirname(__file__), "..", "README.md")

    resp = client.post("/api/run", json={
        "video": os.path.abspath(video),
        "whisper": fake,
        "translator": "qwen2.5:7b",
        "backend": "fasterwhisper",
    })
    assert resp.status_code == 200, resp.status_code
    job_id = resp.get_json()["job_id"]
    assert job_id and job_id in JOBS, "job_id 未被服务端记录"

    # 轮询直到终态
    final = None
    for _ in range(60):
        r = client.get(f"/api/status/{job_id}")
        assert r.status_code == 200
        final = r.get_json()
        if final["status"] in ("done", "failed"):
            break
        time.sleep(0.5)

    assert final["status"] == "failed", final
    assert "model.bin" in final["log"] or "Traceback" in final["log"], \
        "失败日志中应包含模型加载错误"
    print("[OK] run->status(failed) 流程通过，job_id =", job_id)


def test_status_unknown_job():
    client = app.test_client()
    r = client.get("/api/status/doesnotexist")
    assert r.status_code == 404
    print("[OK] 未知 job 返回 404")


def test_download_endpoint_success():
    client = app.test_client()
    job_id = "testdone01"
    srt = os.path.join(OUTPUT, "test_done.srt")
    md = os.path.join(OUTPUT, "test_done.md")
    with open(srt, "w") as f:
        f.write("1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n")
    with open(md, "w") as f:
        f.write("# 测试文稿\n\n内容\n")
    JOBS[job_id] = {"status": "done", "log": "", "srt": srt, "md": md, "cmd": "x"}
    try:
        r = client.get(f"/api/file/{job_id}/srt")
        assert r.status_code == 200, r.status_code
        assert "测试字幕" in r.get_data(as_text=True), "SRT 内容应可下载"
        r = client.get(f"/api/file/{job_id}/md")
        assert r.status_code == 200
        assert "测试文稿" in r.get_data(as_text=True), "MD 内容应可下载"
        # 文件不存在的 job_id 返回 404
        JOBS[job_id + "x"] = {"status": "running", "log": "", "srt": "/nope.srt", "md": "/nope.md", "cmd": "x"}
        r = client.get(f"/api/file/{job_id + 'x'}/srt")
        assert r.status_code == 404
    finally:
        for p in (srt, md):
            if os.path.exists(p):
                os.remove(p)
        JOBS.pop(job_id, None)
        JOBS.pop(job_id + "x", None)
    print("[OK] 下载端点（成功/404）通过")


def test_upload_endpoint():
    client = app.test_client()
    data = b"\x00\x01\x02dummy-video-bytes"
    r = client.post("/api/upload",
                    data={"file": (io.BytesIO(data), "my_clip.mp4")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.status_code
    j = r.get_json()
    assert j["path"] and os.path.exists(j["path"]), "上传文件应落地到 uploads/"
    assert j["size"] == len(data)
    # 同名再传应自动改名
    r2 = client.post("/api/upload",
                     data={"file": (io.BytesIO(data), "my_clip.mp4")},
                     content_type="multipart/form-data")
    assert r2.get_json()["name"] == "my_clip_1.mp4", "同名应自动加后缀"
    # 无文件应 400
    r3 = client.post("/api/upload")
    assert r3.status_code == 400
    # 清理
    for p in (j["path"], r2.get_json()["path"]):
        if os.path.exists(p):
            os.remove(p)
    print("[OK] 上传端点（落地/改名/空文件400）通过")


def test_convert_vtt2srt():
    client = app.test_client()
    vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello world, this is a test.\n\n"
           "00:00:05.000 --> 00:00:08.000\nSecond cue here.\n")
    r = client.post("/api/convert",
                    data={"file": (io.BytesIO(vtt.encode("utf-8")), "demo.vtt"),
                          "mode": "vtt2srt"},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.status_code
    job_id = r.get_json()["job_id"]
    assert job_id in JOBS, "convert job 未记录"

    final = None
    for _ in range(30):
        rr = client.get(f"/api/status/{job_id}")
        final = rr.get_json()
        if final["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert final["status"] == "done", "vtt2srt 应秒级完成: " + final.get("log", "")
    assert "00:00:01,000 --> 00:00:04,000" in (final["srt"] or ""), "SRT 时间轴应保留"
    assert "Hello world" in (final["srt"] or ""), "文本应保留"
    # 下载
    d = client.get(f"/api/file/{job_id}/srt")
    assert d.status_code == 200
    # 清理
    for p in (JOBS[job_id].get("srt"),):
        if p and os.path.exists(p):
            os.remove(p)
    JOBS.pop(job_id, None)
    print("[OK] VTT→SRT 端点通过")


def test_convert_en2zh():
    client = app.test_client()
    srt = ("1\n00:00:01,000 --> 00:00:04,000\n"
           "Great screen and roll action, the big man rolls to the rim.\n\n"
           "2\n00:00:05,000 --> 00:00:09,000\n"
           "He catches the outlet pass and attacks the basket.\n")
    r = client.post("/api/convert",
                    data={"file": (io.BytesIO(srt.encode("utf-8")), "en_demo.srt"),
                          "mode": "en2zh", "translator": "qwen2.5:7b"},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.status_code
    job_id = r.get_json()["job_id"]
    final = None
    for _ in range(120):
        rr = client.get(f"/api/status/{job_id}")
        final = rr.get_json()
        if final["status"] in ("done", "failed"):
            break
        time.sleep(1.0)
    assert final["status"] == "done", "en2zh 应完成: " + final.get("log", "")
    assert any(ord(c) > 0x4e00 for c in (final["srt"] or "")), "SRT 应包含中文"
    assert "中文译文" in (final["md"] or ""), "MD 应为中文译文"
    # 清理
    for p in (JOBS[job_id].get("srt"), JOBS[job_id].get("md")):
        if p and os.path.exists(p):
            os.remove(p)
    JOBS.pop(job_id, None)
    print("[OK] 英文→中文 端点通过")


if __name__ == "__main__":
    test_run_status_failed_flow()
    test_status_unknown_job()
    test_download_endpoint_success()
    test_upload_endpoint()
    test_convert_vtt2srt()
    test_convert_en2zh()
    print("ALL WEB TESTS PASSED")
