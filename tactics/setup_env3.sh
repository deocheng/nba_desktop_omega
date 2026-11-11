#!/bin/bash
# RelateAnything 依赖安装 —— 绕过 editable build（沙箱拦 rename）
set -e
export PYTHONPATH=""
export PIP_DISABLE_PIP_VERSION_CHECK=1

ROOT=/Volumes/12T/NBA/action_analysis
V="$ROOT/.venv"
PIP="$V/bin/python -m pip"

echo "[1/2] install runtime deps (按 pyproject 钉的版本)"
$PIP install \
  "torch~=2.13" \
  "torchvision~=0.28" \
  "transformers~=5.14" \
  "numpy~=2.5" \
  "Pillow~=12.3" \
  "opencv-python-headless~=5.0" \
  "scipy~=1.18" \
  "safetensors~=0.8" \
  "tqdm~=4.68" \
  "huggingface_hub~=1.23"

echo "[2/2] import check"
cd "$ROOT/RelateAnything"
PYTHONPATH="$ROOT/RelateAnything" "$V/bin/python" - <<'PYEOF'
import sys
print("python", sys.version.split()[0])
import torch, transformers, numpy, PIL
print("torch", torch.__version__, "| mps", torch.backends.mps.is_available())
print("transformers", transformers.__version__)
print("numpy", numpy.__version__, "| pillow", PIL.__version__)
try:
    import relsgg
    print("relsgg OK ->", relsgg.__file__)
    from relsgg import RelateAnything
    print("RelateAnything import OK")
except Exception as e:
    print("relsgg import FAIL:", type(e).__name__, e)
PYEOF

echo "DEPS_DONE"
