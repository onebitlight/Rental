#!/bin/bash
# 静态网页服务器启动脚本 — 根目录 /Volumes/Data2TB/rent，端口 8765
# 由 launchd 常驻守护，进程崩溃/被杀会自动重启
# 注意：不要 cd 到外接卷（macOS launchd 下 getcwd 对外接 APFS 受限），
#       用显式 --directory 参数指定根目录。
ROOT_DIR="${RENT_ROOT:-/Volumes/Data2TB/rent}"
PORT="${RENT_PORT:-8765}"
LOG_DIR="/Users/SGY/BelgradeRentals/logs"
mkdir -p "$LOG_DIR"

# 等待外接硬盘挂载（最多等 90 秒，避免开机时硬盘未就绪导致启动失败）
for i in $(seq 1 30); do
  if [ -d "$ROOT_DIR" ]; then break; fi
  sleep 3
done

if [ ! -d "$ROOT_DIR" ]; then
  echo "[$(date '+%F %T')] FATAL: root dir $ROOT_DIR not mounted" >> "$LOG_DIR/serve_static.log"
  exit 1
fi

echo "[$(date '+%F %T')] Serving $ROOT_DIR on 127.0.0.1:$PORT" >> "$LOG_DIR/serve_static.log"
# 关键修复：留在当前 CWD（家目录），用 --directory 显式指定根目录，避开对外接卷的 getcwd 限制
exec /usr/bin/python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$ROOT_DIR"
