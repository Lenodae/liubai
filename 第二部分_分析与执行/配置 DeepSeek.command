#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/代码"
python3 tools/configure_deepseek.py
printf '\n按回车关闭窗口。'
read -r _ || true
