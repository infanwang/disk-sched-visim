#!/usr/bin/env bash
# 磁盘调度仿真 · 一键部署（macOS / Linux）
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for cand in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
      PY="$cand"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "！没有找到 Python 3.9+，请先安装：https://www.python.org/downloads/"
  exit 1
fi

echo
echo "  磁盘调度仿真 · 一键部署"
echo "  ────────────────────────────────────────"
exec "$PY" deploy.py "$@"
