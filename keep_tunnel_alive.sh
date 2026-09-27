#!/bin/bash
# 贝尔格莱德租房 — Cloudflare 隧道守护保活脚本
# 用法: nohup bash keep_tunnel_alive.sh &  或设置 LaunchAgent 自动启动
#
# 每 30 秒检测网络 → 隧道进程 → 域名可达性
# 失效则自动重启 tunnel + 更新 guardian_state.json

set -e

BASE="$HOME/BelgradeRentals"
LOG="$BASE/logs/keep_alive.log"
STATE="$BASE/logs/guardian_state.json"
TUNNEL_LOG="/tmp/cloudflared.log"
PORT="8765"
CHECK_INTERVAL=30          # 检测间隔（秒）
NET_PING_HOST="8.8.8.8"

mkdir -p "$(dirname "$LOG")" "$(dirname "$STATE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# ---------- 工具函数 ----------
net_ok() {
    if ping -c 1 -W 3 "$NET_PING_HOST" >/dev/null 2>&1; then return 0; else return 1; fi
}

tunnel_proc_alive() {
    pgrep -f "cloudflared tunnel" >/dev/null 2>&1
}

# 从日志提取最新 trycloudflare.com 域名
extract_url() {
    grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1
}

# 探测域名是否可访问
url_reachable() {
    local url="$1"
    [ -z "$url" ] && return 1
    curl -sS -m 10 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null | grep -q "^2"
}

# 更新 guardian_state.json
update_state() {
    local url="$1"
    cat > "$STATE" <<EOF
{"ts":$(date +%s),"static_up":1,"tunnel_up":1,"public_url":"$url"}
EOF
    log "✅ guardian_state.json 已更新: $url"
}

# 静态服务启动（若端口未被占用）
start_static() {
    if lsof -i ":$PORT" >/dev/null 2>&1; then
        return 0  # 已运行
    fi
    log "启动静态服务 (:$PORT, root=/Volumes/Data2TB/rent)..."
    nohup python3 -m http.server "$PORT" --directory /Volumes/Data2TB/rent --bind 127.0.0.1 > /tmp/static_server.log 2>&1 &
    sleep 2
}

# ---------- 主循环 ----------
log "===== 隧道守护启动 间隔=${CHECK_INTERVAL}s ====="

while true; do
    # 0. 网络检测
    if ! net_ok; then
        log "⏳ 无网络 ($NET_PING_HOST)，等待恢复..."
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # 1. 静态服务
    start_static

    # 2. 检查当前隧道状态
    if tunnel_proc_alive; then
        cur_url=$(extract_url)
        if [ -n "$cur_url" ] && url_reachable "$cur_url"; then
            # 正常：更新 state 并继续等待
            update_state "$cur_url"
            sleep "$CHECK_INTERVAL"
            continue
        else
            log "⚠️ 隧道进程存在但域名 $cur_url 不可达，准备重启..."
            pkill -f "cloudflared tunnel" 2>/dev/null || true
        fi
    else
        log "⚠️ 隧道进程不存在，准备启动..."
    fi

    # 3. 启动/重启隧道
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    sleep 2
    log "🚀 启动 Cloudflare 隧道 (-> http://127.0.0.1:$PORT)..."
    > "$TUNNEL_LOG"  # 清空旧日志
    nohup /usr/local/bin/cloudflared tunnel --url "http://127.0.0.1:$PORT" \
        >> "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    log "隧道 PID=$TUNNEL_PID"

    # 等待新域名出现（最长 40 秒）
    new_url=""
    waited=0
    while [ $waited -lt 40 ]; do
        sleep 2
        waited=$((waited + 2))
        new_url=$(extract_url)
        [ -n "$new_url" ] && break
    done

    if [ -n "$new_url" ]; then
        log "拿到新域名: $new_url"
    else
        log "❌ 40s 内未获取到新域名，跳过本轮"
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # 4. 验证新域名可达性
    if url_reachable "$new_url"; then
        update_state "$new_url"
        log "✅ 隧道自愈完成"
    else
        log "❌ 新域名 $new_url 不可达，下轮重试"
    fi

    sleep "$CHECK_INTERVAL"
done