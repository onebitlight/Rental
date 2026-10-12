#!/bin/bash
# 贝尔格莱德租房 — 静态服务器保活守护 (v3: os.chdir 方案，不干预隧道)
# 
# 隧道由系统 LaunchDaemon /Library/LaunchDaemons/com.cloudflare.cloudflared.plist 管理
# 本脚本仅负责静态 HTTP 服务器的保活

set -e

BASE="${HOME}/Projects/BelgradeEstate"
LOG="${BASE}/logs/keep_alive.log"
STATE="${BASE}/logs/guardian_state.json"
PORT="8765"
STATIC_ROOT="/Volumes/Data2TB/ai_output/BelgradeEstate"
CHECK_INTERVAL=30
NET_PING_HOST="8.8.8.8"
FIXED_PUBLIC_URL="https://estate.onebitlight.xyz"

mkdir -p "${BASE}/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG}"; }

net_ok() { ping -c 1 -W 3 "${NET_PING_HOST}" >/dev/null 2>&1; }

update_state() {
    cat > "${STATE}" <<EOF
{"ts":$(date +%s),"static_up":1,"tunnel_up":1,"public_url":"${FIXED_PUBLIC_URL}"}
EOF
    log "✅ guardian_state.json 已更新: ${FIXED_PUBLIC_URL}"
}

start_static() {
    local EXISTING_PID
    EXISTING_PID=$(lsof -ti ":${PORT}" 2>/dev/null | head -1)
    if [ -n "${EXISTING_PID}" ]; then
        local CWD
        CWD=$(lsof -p "${EXISTING_PID}" 2>/dev/null | grep cwd | awk '{print $NF}')
        if [ "${CWD}" = "${STATIC_ROOT}" ]; then
            return 0  # 已在正确目录运行
        fi
        # 路径不对 — 杀死旧进程
        log "⚠️  静态服务运行在错误路径 (${CWD})，重启中..."
        kill "${EXISTING_PID}" 2>/dev/null || true
        sleep 2
    fi

    # 启动：用 os.chdir 内联方案，避免 Python 3.9 --directory 不稳定
    log "🚀 启动静态服务 (:${PORT}, root=${STATIC_ROOT})..."
    cd "${STATIC_ROOT}"
    nohup python3 -c "
import os, http.server, socketserver
os.chdir('${STATIC_ROOT}')
PORT = ${PORT}
Handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(('127.0.0.1', PORT), Handler) as httpd:
    print('Serving ' + os.getcwd() + ' on port ' + str(PORT), flush=True)
    httpd.serve_forever()
" > /tmp/static_server.log 2>&1 &
    sleep 2
    log "✅ 静态服务已启动 (PID: ${!})"
}

log "===== 静态服务守护 v3 启动 (固定域名: ${FIXED_PUBLIC_URL}) ====="
log "注意：Cloudflare 隧道由系统 LaunchDaemon 管理，本脚本仅负责静态服务。"

while true; do
    if ! net_ok; then
        log "⏳ 无网络，等待恢复..."
        sleep "${CHECK_INTERVAL}"
        continue
    fi

    start_static
    update_state
    sleep "${CHECK_INTERVAL}"
done