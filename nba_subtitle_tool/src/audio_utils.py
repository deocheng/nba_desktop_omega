"""音频工具：从视频抽取单声道 16k wav，并按时间分块以支持长视频。"""
import os
import shutil
import subprocess


def _resolve_bin(name: str) -> str:
    """定位 ffmpeg / ffprobe：优先常见 Homebrew / MacPorts 路径，回退到 PATH。
    背景任务（launchd / 清理过的 subprocess 环境）往往 PATH 不含 /opt/homebrew/bin，
    裸调用 "ffmpeg" 会 FileNotFoundError。这里显式解析绝对路径，保证任意启动方式都能跑。"""
    candidates = [
        f"/opt/homebrew/bin/{name}",   # Apple Silicon Homebrew
        f"/usr/local/bin/{name}",      # Intel Homebrew
        f"/opt/local/bin/{name}",      # MacPorts
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    found = shutil.which(name)
    if found:
        return found
    return name  # 最后回退为裸名（依赖 PATH）


_FFMPEG = _resolve_bin("ffmpeg")
_FFPROBE = _resolve_bin("ffprobe")


def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def extract_audio(video_path: str, out_wav: str, sr: int = 16000, channels: int = 1) -> str:
    """用 ffmpeg 从视频抽取音频为单声道 16k wav。"""
    os.makedirs(os.path.dirname(out_wav), exist_ok=True)
    _run([
        _FFMPEG, "-y", "-i", video_path,
        "-vn", "-ac", str(channels), "-ar", str(sr), "-f", "wav", out_wav,
    ])
    return out_wav


def get_duration(path: str) -> float:
    """返回音频/视频时长（秒）。"""
    out = subprocess.check_output([
        _FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ]).decode().strip()
    return float(out)


def chunk_audio(wav_path: str, work_dir: str, chunk_sec: int = 600,
                overlap_sec: int = 20) -> list:
    """把长音频按 chunk_sec 切分（块间重叠 overlap_sec 秒，避免切断句子）。
    返回 [{index, path, offset, start, end}]，offset 为相对原音频起点。"""
    os.makedirs(work_dir, exist_ok=True)
    total = get_duration(wav_path)
    chunks = []
    start = 0.0
    idx = 0
    while start < total - 0.1:
        end = min(start + chunk_sec, total)
        seg_path = os.path.join(work_dir, f"chunk_{idx:04d}.wav")
        dur = end - start
        _run([
            _FFMPEG, "-y", "-i", wav_path,
            "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
            "-ac", "1", "-ar", "16000", "-f", "wav", seg_path,
        ])
        chunks.append({
            "index": idx, "path": seg_path,
            "offset": start, "start": start, "end": end,
        })
        if end >= total:
            break
        start = max(end - overlap_sec, start + 1.0)
        idx += 1
    return chunks
