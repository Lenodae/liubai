#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)/代码"
APP_URL="http://127.0.0.1:8001/"

fail() {
  printf '\n%s\n' "$1"
  printf '按回车关闭窗口。'
  read -r _ || true
  exit 1
}

ready() {
  local page
  page=$(curl -fsS --max-time 2 "$APP_URL" 2>/dev/null) || return 1
  [[ "$page" == *'<title>留白 · 分析与执行</title>'* ]]
}

[[ -f "$PROJECT_DIR/start.sh" ]] || fail "找不到 代码文件夹，请将此入口与代码文件夹放在一起。"
cd "$PROJECT_DIR"

if ! ready; then
  if lsof -t -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1; then
    fail "8001 端口已被其他服务占用。请先关闭占用此端口的程序，再打开留白。"
  fi

  printf '正在启动留白，首次启动可能需要安装依赖，请稍候…\n'
  mkdir -p .local
  chmod 700 .local
  server_pid=$(python3 - <<'LAUNCH_PY'
import subprocess
from pathlib import Path
with Path('.local/server.log').open('ab') as log:
    process = subprocess.Popen(['/bin/bash', './start.sh'], stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
Path('.local/server.pid').write_text(str(process.pid))
print(process.pid)
LAUNCH_PY
)

  while ! ready; do
    if ! kill -0 "$server_pid" 2>/dev/null; then
      printf '\n启动日志：\n'
      tail -n 15 .local/server.log
      fail "留白未能启动。详细日志位于 代码/.local/server.log。"
    fi
    sleep 1
  done
fi

if ! /usr/bin/open "$APP_URL"; then
  fail "服务已启动，请在浏览器手动打开 $APP_URL"
fi
printf '\n留白已打开：%s\n可以关闭此终端窗口，服务会继续在后台运行。\n' "$APP_URL"
