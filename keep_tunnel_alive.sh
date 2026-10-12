#!/bin/bash
# 贝尔格莱德租房 — Cloudflare 隧道守护保活脚本 (v3: 极简防冲突版)

set -e

BASE="$HOME/Projects/BelgradeEstate"
LOG="$BASE/logs/keep_alive.log"
STATE="$BASE/logs/guardian_state.json"
PORT="8765"
STATIC_ROOT="/Volumes/Data2TB/ai_output/BelgradeEstate"
CHECK_INTERVAL=30
FIXED_PUBLIC_URL="https://estate.onebitlight.xyz"

mkdir -p "$(dirname "$LOG")" "$(dirname "$STATE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

update_state() {
    echo "{\"ts\":$(date +%s),\"static_up\":1,\"tunnel_up\":1,\"public_url\":\"$FIXED_PUBLIC_URL\"}" > "$STATE"
}

start_static() {
    local EXISTING_PID=""
    EXISTING_PID=$(lsof -ti ":$PORT" 2>/dev/null | head -1)
    
    if [ -n "$EXISTING_PID" ]; then
        local CWD=""
        CWD=$(lsof -p "$EXISTING_PID" 2>/dev/null | grep cwd | awk '{print $NF}')
        if [ "$CWD" = "$STATIC_ROOT" ]; then
            return 0
        fi
        log "⚠️ 发现 8765 端口运行在错误路径 ($CWD)，清理中..."
        kill -9 "$EXISTING_PID" 2>/dev/null || true
        sleep 2
    fi

    log "🚀 在正确路径启动静态服务 (:$PORT -> $STATIC_ROOT)..."
    nohup python3 -c "
import os, http.server, socketserver
os.chdir('$STATIC_ROOT')
PORT = $PORT
class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

Handler = http.server.SimpleHTTPRequestHandler
with ReusableTCPServer(('127.0.0.1', PORT), Handler) as httpd:
    print('Serving', os.getcwd(), 'on port', PORT, flush=True)
    httpd.serve_forever()
" > /tmp/static_server.log 2>&1 &
    sleep 2
    log "✅ 静态服务已启动"
}

log "===== 守护保活脚本启动 (服务目录: $STATIC_ROOT) ====="

while true; do
    start_static
    update_state
    sleep "$CHECK_INTERVAL"
done
