#!/bin/bash
# 贝尔格莱德租房 · 服务守护脚本
# 由 OpenClaw automation 每 5 分钟调用一次（gateway 常驻，绕开 launchd 的 TCC 外接卷限制）
# 职责：
#   1. 确保本地静态服务器（127.0.0.1:8765  <- /Volumes/Data2TB/rent）存活，挂了就拉起
#   2. 确保 cloudflared 公网隧道存活，挂了就拉起并抓取新 URL
#   3. 把最新公网 URL 写入 logs/tunnel_url.txt
#   4. 探测公网可达性，把状态写进 logs/guardian_state.json

set +e

PORT=8765
ROOT_DIR="/Volumes/Data2TB/rent"
CF="/usr/local/bin/cloudflared"
LOG_DIR="/Users/SGY/BelgradeRentals/logs"
ULOG="$LOG_DIR/tunnel_url.txt"
STATE="$LOG_DIR/guardian_state.json"
mkdir -p "$LOG_DIR"

now_ts=$(date +%s)

# ---- 1) 本地静态服务器 ----
static_up=0
if curl -s -o /dev/null --max-time 4 "http://127.0.0.1:$PORT/" 2>/dev/null; then
  static_up=1
else
  if ! lsof -i :"$PORT" >/dev/null 2>&1; then
    nohup /usr/bin/python3 -m http.server "$PORT" --bind 127.0.0.1 \
      --directory "$ROOT_DIR" >> "$LOG_DIR/serve_stdout.log" 2>&1 &
    sleep 4
  fi
  if curl -s -o /dev/null --max-time 4 "http://127.0.0.1:$PORT/" 2>/dev/null; then
    static_up=1
  fi
fi

# ---- 2) cloudflared 隧道 ----
tunnel_up=0
current_url=""
tunnel_proc="cloudflared tunnel --url http://127.0.0.1:$PORT"
if pgrep -f "$tunnel_proc" >/dev/null 2>&1; then
  [ -f "$ULOG" ] && current_url=$(cat "$ULOG")
  if [ -n "$current_url" ] && curl -s -o /dev/null --max-time 8 "$current_url/" 2>/dev/null; then
    tunnel_up=1
  fi
fi

if [ "$tunnel_up" -eq 0 ]; then
  pkill -f "$tunnel_proc" 2>/dev/null
  sleep 1
  # 后台起隧道并持续抓 URL 写文件
  nohup bash -c 'cd /tmp && exec '"$CF"' tunnel --url http://127.0.0.1:'"$PORT"' --no-autoupdate 2>&1 | while IFS= read -r line; do echo "$line" >> "'"$LOG_DIR"'/tunnel_daemon.log"; u=$(echo "$line" | grep -oE "https://[a-zA-Z0-9-]+\\.trycloudflare\\.com" | head -1); if [ -n "$u" ]; then echo "$u" > "'"$ULOG"'"; fi; done' >> "$LOG_DIR/tunnel_daemon.log" 2>&1 &
  # 等待新 URL（最多 24 秒）
  for i in $(seq 1 12); do
    sleep 2
    nb=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$ULOG" 2>/dev/null | tail -1)
    if [ -n "$nb" ] && curl -s -o /dev/null --max-time 6 "$nb/" 2>/dev/null; then
      current_url="$nb"; tunnel_up=1; break
    fi
  done
fi

# ---- 3) 组装状态写入文件 ----
printf '{"ts":%s,"static_up":%d,"tunnel_up":%d,"public_url":"%s"}\n' \
  "$now_ts" "$static_up" "$tunnel_up" "$current_url" > "$STATE"

echo "static_up=$static_up tunnel_up=$tunnel_up url=$current_url"
