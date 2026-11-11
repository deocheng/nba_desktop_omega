"""VLX-Seek 1.5 PoC: falsify whether a 4-bit/MPS 10B can distinguish
a dead-ball referee stoppage close-up (cand1244) from a live-ball
offensive close-up (cand932 / possA).

Runs vqa (no bbox needed) on one representative frame per candidate and
compares the LIVE/DEAD answer against 老程's visual verdict.
"""
import os
import sys

from PIL import Image
from vlx_seek_worker import VLXSeekWorker

try:
    from torchao.quantization import Int4WeightOnlyConfig
    from transformers import TorchAoConfig
except Exception as e:  # pragma: no cover
    TorchAoConfig = None
    print("TorchAoConfig import failed:", e)

REPO = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(REPO, "resources", "VLX-Seek-1.5-10B")
DEVICE = "mps"

QCFG = None
if TorchAoConfig is not None:
    try:
        QCFG = TorchAoConfig(Int4WeightOnlyConfig(group_size=32))
    except Exception as e:
        print("TorchAoConfig(Int4WeightOnlyConfig) failed:", e)

print(f"[poc] loading worker device={DEVICE} quant={QCFG} model={MODEL}", flush=True)
worker = VLXSeekWorker(MODEL, device=DEVICE, quantization_config=QCFG)

FRAMES = {
    "cand1244 (裁定=DEAD/吹停)": "/tmp/poc/cand_1244.5-1269.0.jpg",
    "cand932  (裁定=LIVE/活球)": "/tmp/poc/cand_932.5-949.0.jpg",
    "possA    (裁定=LIVE/活球)": "/tmp/poc/possA_full_444.5-458.0.jpg",
}

QUESTION = (
    "In this NBA broadcast frame, is the on-court action a live-ball "
    "offensive possession, or a dead-ball stoppage such as a referee "
    "whistle, timeout, or transition? Reply with exactly one word: "
    "LIVE or DEAD."
)

for name, path in FRAMES.items():
    if not os.path.exists(path):
        print(f"[{name}] MISSING {path}")
        continue
    img = Image.open(path).convert("RGB")
    try:
        r = worker.predict(img, QUESTION, max_new_tokens=32, temperature=0.0)
        ans = r.get("answer", "").strip()
    except Exception as e:
        ans = f"ERROR: {e}"
    print(f"\n[{name}] -> {ans!r}", flush=True)
print("\n[poc] done", flush=True)
