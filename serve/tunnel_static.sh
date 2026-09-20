#!/bin/bash
# cloudflared 隧道守护脚本 — 把本地 8765 端口暴露到公网
# 由 launchd 常驻守护：进程退出/隧道中断会自动重启并重新获取新 URL
LOG_DIR="/Users/SGY/BelgradeRentals/logs"
ULOG="$LOG_DIR/tunnel_url.txt"
mkdir -p "$LOG_DIR"

# 可选：命名隧道固定域名（当你有 Cloudflare 证书后启用）
# CF_TUNNEL_NAME="rent"
# CLOUDFLARED_TUNNEL_ID="你的tunnel-id"  # 从 cloudflared tunnel create 获取

CF="/usr/local/bin/cloudflared"

echo "[$(date '+%F %T')] tunnel daemon start" >> "$LOG_DIR/tunnel_daemon.log"

# 先确认本地服务器活着，否则等它
for i in $(seq 1 20); do
  if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8765/ ; then break; fi
  sleep 3
done

while true; do
  echo "[$(date '+%F %T')] starting tunnel..." >> "$LOG_DIR/tunnel_daemon.log"
  # 生成固定格式的 URL 日志（命名隧道启用时改为你的固定域名）
  if [ -n "$CF_TUNNEL_NAME" ] && [ -n "$CLOUDFLARED_TUNNEL_ID" ]; then
    echo "https://rent.example.com" > "$ULOG"
    exec "$CF" tunnel --config /Users/SGY/BelgradeRentals/serve/cloudflared.yml run "$CF_TUNNEL_NAME"
  else
    # trycloudflare 临时隧道：解析新 URL 写入日志
    "$CF" tunnel --url http://127.0.0.1:8765 --no-autoupdate \
      | while IFS= read -r line; do
          echo "$line" >> "$LOG_DIR/tunnel_daemon.log"
          url=$(echo "$line" | grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' | head -1)
          if [ -n "$url" ]; then
            echo "$url" > "$ULOG"
            echo "[$(date '+%F %T')] NEW URL: $url" >> "$LOG_DIR/tunnel_daemon.log"
          fi
        done
  fi
  echo "[$(date '+%F %T')] tunnel exited, restarting in 5s..." >> "$LOG_DIR/tunnel_daemon.log"
  sleep 5
done
