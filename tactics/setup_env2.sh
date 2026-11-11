#!/bin/bash
# RelateAnything 安装（跳过已完成的 venv 创建）
set -e
export PYTHONPATH=""
export PIP_DISABLE_PIP_VERSION_CHECK=1

ROOT=/Volumes/12T/NBA/action_analysis
V="$ROOT/.venv"
PIP="$V/bin/python -m pip"

echo "[check] venv"
$V/bin/python -V

echo "[1/2] install relsgg[hub]"
cd "$ROOT/RelateAnything"
$PIP install -e ".[hub]"

echo "[2/2] version report"
$V/bin/python - <<'PYEOF'
import sys, torch, transformers
print("python", sys.version.split()[0])
print("torch", torch.__version__, "| mps", torch.backends.mps.is_available())
print("transformers", transformers.__version__)
PYEOF

echo "INSTALL_DONE"
