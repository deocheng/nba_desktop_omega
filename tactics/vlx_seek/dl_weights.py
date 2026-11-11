import os

from huggingface_hub import snapshot_download

REPO = "omlab/VLX-Seek-1.5-10B"
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "VLX-Seek-1.5-10B")
os.makedirs(LOCAL, exist_ok=True)
print(f"[dl] repo={REPO} local={LOCAL}", flush=True)
p = snapshot_download(REPO, local_dir=LOCAL, local_dir_use_symlinks=False)
print("DONE", p, flush=True)
