#!/usr/bin/env python3
"""本地 Web UI：NBA 视频 → 中文字幕/文稿。
启动：python web.py  →  浏览器打开 http://localhost:7860

提交方式：
  - 拖拽文件到页面（自动上传到本机临时目录后处理）
  - 点「选择文件」用系统文件选择器（自动上传）
  - 直接填写本机绝对路径（免上传，适合 12T 上已存在的大视频）
"""
import os
import sys
import io
import uuid
import threading
import subprocess
from werkzeug.utils import secure_filename

from flask import (Flask, request, jsonify, send_file)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from src.pipeline import load_config

app = Flask(__name__, template_folder=os.path.join(HERE, "webui"),
            static_folder=os.path.join(HERE, "webui"))

# 本地服务，放宽上传上限（50GB，足够 5 小时视频）
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024 * 1024

WORK = os.path.join(HERE, "work")
OUTPUT = os.path.join(HERE, "output")
UPLOAD_DIR = os.path.join(WORK, "uploads")
os.makedirs(WORK, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

JOBS = {}  # job_id -> {status, log, srt, md, cmd, rc}


def _ollama_models():
    try:
        out = subprocess.check_output(["ollama", "list"],
                                      stderr=subprocess.DEVNULL).decode()
        models = []
        for line in out.splitlines()[1:]:
            name = line.split()[0]
            if name:
                models.append(name)
        return models
    except Exception:
        return []


def _local_whisper():
    mdir = os.path.join(HERE, "models")
    res = []
    if os.path.isdir(mdir):
        for d in sorted(os.listdir(mdir)):
            p = os.path.join(mdir, d)
            if os.path.isdir(p) and os.path.exists(os.path.join(p, "model.bin")):
                res.append({"name": d, "path": p})
    return res


@app.route("/")
def index():
    return send_file(os.path.join(HERE, "webui", "index.html"))


@app.route("/api/info")
def api_info():
    cfg = load_config(os.path.join(HERE, "config.yaml"))
    return jsonify({
        "ollama_models": _ollama_models(),
        "local_whisper": _local_whisper(),
        "default_translator": cfg["models"].get("translator"),
        "default_whisper": cfg["models"].get("whisper"),
        "default_backend": cfg["models"].get("backend", "fasterwhisper"),
    })


@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "未收到文件"}), 400
    base = secure_filename(f.filename) or "upload.bin"
    stem, ext = os.path.splitext(base)
    dest = os.path.join(UPLOAD_DIR, base)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(UPLOAD_DIR, f"{stem}_{i}{ext}")
        i += 1
    f.save(dest)
    return jsonify({
        "path": dest,
        "name": os.path.basename(dest),
        "size": os.path.getsize(dest),
    })


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.json or {}
    video = data.get("video", "")
    if not video or not os.path.exists(video):
        return jsonify({"error": "视频文件不存在或路径为空"}), 400

    job_id = uuid.uuid4().hex[:8]
    log_path = os.path.join(WORK, f"job_{job_id}.log")
    # 输出与源视频同目录（VLC/Infuse 可自动加载），目录不存在则回退到 output/
    out_dir = os.path.dirname(video) or OUTPUT
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(video))[0]
    srt_path = os.path.join(out_dir, f"{base}.srt")
    md_path = os.path.join(out_dir, f"{base}.md")
    for p in (srt_path, md_path):
        if os.path.exists(p):
            os.remove(p)

    cmd = [sys.executable, os.path.join(HERE, "run.py"),
           "--video", video, "--output", out_dir]
    if data.get("whisper"):
        cmd += ["--whisper", data["whisper"]]
    if data.get("translator"):
        cmd += ["--translator", data["translator"]]
    if data.get("backend"):
        cmd += ["--backend", data["backend"]]

    JOBS[job_id] = {"status": "running", "log": log_path,
                    "srt": srt_path, "md": md_path, "cmd": " ".join(cmd),
                    "kind": "transcribe"}

    with open(log_path, "w") as f:
        f.write("启动命令: " + " ".join(cmd) + "\n")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=1,
                            universal_newlines=True, cwd=HERE)
    _start_pump(job_id, proc, [srt_path, md_path])
    return jsonify({"job_id": job_id})


def _start_pump(job_id, proc, expect):
    """通用日志泵：子进程结束后，根据期望产物是否齐全 + 退出码判定完成/失败。"""
    log_path = JOBS[job_id]["log"]

    def _pump():
        with open(log_path, "a") as lf:
            for line in proc.stdout:
                lf.write(line)
            if proc.stdout:
                proc.stdout.close()
            rc = proc.wait()
        ok = (rc == 0) and all(os.path.exists(p) for p in (expect or []))
        JOBS[job_id]["status"] = "done" if ok else "failed"
        JOBS[job_id]["rc"] = rc

    threading.Thread(target=_pump, daemon=True).start()


@app.route("/api/convert", methods=["POST"])
def api_convert():
    """字幕/文本转换：multipart 表单，支持 file 直传或 path 指向已上传文件。
    字段：file(可选) / path(可选) / mode(vtt2srt|en2zh) / translator(可选)。"""
    mode = request.form.get("mode", "vtt2srt")
    translator = request.form.get("translator", "")
    if mode not in ("vtt2srt", "en2zh"):
        return jsonify({"error": "未知模式"}), 400

    f = request.files.get("file")
    path = request.form.get("path", "").strip()
    if (not f or not f.filename) and not path:
        return jsonify({"error": "未收到文件"}), 400

    if f and f.filename:
        base = secure_filename(f.filename) or "upload.bin"
        stem, ext = os.path.splitext(base)
        dest = os.path.join(UPLOAD_DIR, base)
        i = 1
        while os.path.exists(dest):
            dest = os.path.join(UPLOAD_DIR, f"{stem}_{i}{ext}")
            i += 1
        f.save(dest)
        path = dest
        ext = os.path.splitext(path)[1].lower()
    else:
        stem = os.path.splitext(os.path.basename(path))[0]
        ext = os.path.splitext(path)[1].lower()

    out_dir = UPLOAD_DIR
    job_id = uuid.uuid4().hex[:8]
    log_path = os.path.join(WORK, f"job_{job_id}.log")

    srt_path = md_path = None
    expect = []
    if mode == "vtt2srt":
        srt_path = os.path.join(out_dir, stem + ".srt")
        expect = [srt_path]
    else:  # en2zh
        if ext in (".srt", ".vtt"):
            srt_path = os.path.join(out_dir, stem + ".zh.srt")
        md_path = os.path.join(out_dir, stem + ".zh.md")
        expect = [md_path] + ([srt_path] if srt_path else [])

    for p in (srt_path, md_path):
        if p and os.path.exists(p):
            os.remove(p)

    cmd = [sys.executable, os.path.join(HERE, "convert_cli.py"),
           "--input", path, "--mode", mode,
           "--out-srt", srt_path or "", "--out-md", md_path or "",
           "--translator", translator]
    JOBS[job_id] = {"status": "running", "log": log_path,
                    "srt": srt_path, "md": md_path,
                    "cmd": " ".join(cmd), "kind": "convert"}

    with open(log_path, "w") as lf:
        lf.write(f"模式: {mode}\n输入: {path}\n命令: {' '.join(cmd)}\n")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=1,
                            universal_newlines=True, cwd=HERE)
    _start_pump(job_id, proc, expect)
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "未知任务"}), 404
    log = ""
    try:
        with open(job["log"], "r", encoding="utf-8", errors="replace") as f:
            log = "".join(f.readlines()[-200:])
    except Exception:
        pass
    srt = md = None
    if job["status"] == "done":
        try:
            with open(job["srt"], "r", encoding="utf-8") as f:
                srt = f.read()
            with open(job["md"], "r", encoding="utf-8") as f:
                md = f.read()
        except Exception:
            pass
    return jsonify({
        "status": job["status"], "log": log, "srt": srt, "md": md,
        "srt_name": os.path.basename(job["srt"]) if job.get("srt") else None,
        "md_name": os.path.basename(job["md"]) if job.get("md") else None,
    })


@app.route("/api/file/<job_id>/<ext>")
def api_file(job_id, ext):
    job = JOBS.get(job_id)
    if not job:
        return "unknown", 404
    p = job["srt"] if ext == "srt" else job["md"]
    if not os.path.exists(p):
        return "not ready", 404
    return send_file(p, as_attachment=True,
                     download_name=os.path.basename(p))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"NBA 字幕工具 Web UI  →  http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
