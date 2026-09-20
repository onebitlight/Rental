#!/usr/bin/env python3
"""
Belgrade Rental — 微信动态推送脚本（底层 CLI 方式，不依赖大模型路由工具）

用法:
    python3 send_wechat.py <实际套数> <最新URL> [--tail "末尾追加行"]

示例:
    python3 send_wechat.py 2 "https://example.com/"
    python3 send_wechat.py 7 "https://example.com/"
    python3 send_wechat.py 0 ""                      # 零房源保底推送(无链接)
    python3 send_wechat.py 0 "" --tail "📢 本轮10天定时推送任务已全部执行完毕，如需继续请告诉我！"

参数:
    <套数>   动态房源数（整数），写入标题「（N套）」
    <URL>    动态生成的 HTML / Cloudflare 隧道 URL（纯文本链接）

行为:
    1. 内置 WECHAT_TARGETS 白名单数组（可随时增删微信号）。
    2. 用 subprocess 调用底层 CLI:
         openclaw message send --channel openclaw-weixin --target <TARGET> --message <文本>
    3. 依次向每个目标遍历推送。

已验证的实际 CLI 语法（2026-09-14 dry-run 通过，channel openclaw-weixin 可直接使用）:
    openclaw message send --channel openclaw-weixin --target "xxx@im.wechat" --message "文本"
    4. 推送文本严格使用纯文本模板（严禁 card.png / 摘要列表）:
         🏡 <日期> 贝尔格莱德好房精选（<套数>套）

         详情请点击链接👇：
         🔗 <URL>
    5. 无 URL 或 URL 为空时跳过链接行，仅保留标题行。

【URL 必须是对外可点击访问的公网地址】
- <URL> 必须是真实可达的公网链接（如 cloudflared 隧道 https://xxx.trycloudflare.com/friend_push.html 或 Portal 公网 URL），
  切勿传 127.0.0.1 / localhost 本机地址——手机微信里点不开。
- 每日流程：抓取 -> 渲染当日 friend_push.html 并复制到 ~/BelgradeRentals/public/ ->
  cloudflared 隧道 / Portal 获取公网 URL -> 运行本脚本传该 URL。
"""
import subprocess
import sys
import time
import datetime


# ---------------------------------------------------------------------------
# 微信目标白名单：可随时向此数组追加新微信号
# ---------------------------------------------------------------------------
WECHAT_TARGETS = [
    "o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat",
]

CHANNEL = "openclaw-weixin"


def build_message(count: int, url: str, tail: str = "") -> str:
    """构造严格纯文本格式的推送内容。

    count>0: 标题 + 链接行。
    count==0: 零房源保底文案（无链接，非静默）。
    tail: 非空时在末尾追加该行（用于第10天终结提醒）。
    """
    today = datetime.date.today().strftime("%Y年%m月%d日")
    if count <= 0:
        lines = [
            f"🏡 {today} 贝尔格莱德好房精选（0套）",
            "",
            "今日未检索到符合条件的全新房源，请明日继续关注！",
        ]
    else:
        lines = [
            f"🏡 {today} 贝尔格莱德好房精选（{count}套）",
            "",
            "详情请点击链接👇：",
        ]
        if url and url.strip():
            lines.append(f"🔗 {url.strip()}")
    if tail and tail.strip():
        lines.append("")
        lines.append(tail.strip())
    return "\n".join(lines)


PUSH_ATTEMPTS = 3          # 单目标最多尝试次数
PUSH_TIMEOUT = 120         # 单次 CLI 调用超时（秒）
RETRY_BACKOFF = 5          # 失败后重试间隔（秒）


def push(target: str, text: str, attempts: int = PUSH_ATTEMPTS) -> bool:
    """用 subprocess 调用底层 CLI 向单个目标推送；带重试与退避，返回是否成功。

    每次调用均携带 --channel，超时 120 秒；失败后间隔 RETRY_BACKOFF 重试。
    任一尝试成功即返回 True（rc==0 视为 CLI 正常退出、送达成功）。
    """
    cmd = [
        "openclaw", "message", "send",
        "--channel", CHANNEL,
        "--target", target,
        "--message", text,
    ]
    for attempt in range(1, attempts + 1):
        print(f"[push] channel={CHANNEL} target={target} attempt={attempt}/{attempts}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=PUSH_TIMEOUT)
        except Exception as e:
            print(f"[push] EXCEPTION {target} attempt={attempt}: {e}", file=sys.stderr)
            proc = None

        if proc is not None:
            tail = (proc.stdout or "").strip().splitlines()
            tail = tail[-3:] if tail else []
            tail += (proc.stderr or "").strip().splitlines()[-3:]
            print("[push] rc=%s" % proc.returncode)
            for line in tail:
                print(f"[push] | {line}")
            if proc.returncode == 0:
                return True

        if attempt < attempts:
            time.sleep(RETRY_BACKOFF)
    return False


def push_all(text: str, attempts: int = PUSH_ATTEMPTS) -> bool:
    """向白名单中所有目标推送同一文本；全部成功才返回 True。

    供 scraper.py 等复用：携带 --channel + 120s 超时 + 健壮重试。
    """
    ok_all = True
    for t in WECHAT_TARGETS:
        ok = push(t, text, attempts=attempts)
        ok_all = ok_all and ok
    return ok_all


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    try:
        count = int(sys.argv[1])
    except ValueError:
        print("[err] 套数必须为整数", file=sys.stderr)
        return 2

    url = sys.argv[2] if len(sys.argv) >= 3 and sys.argv[2] else ""
    tail = ""
    if "--tail" in sys.argv:
        i = sys.argv.index("--tail")
        tail = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""

    text = build_message(count, url, tail)
    print("---- 待推送文本 ----")
    print(text)
    print("--------------------")

    ok_all = push_all(text)

    if ok_all:
        print(f"[done] 已向 {len(WECHAT_TARGETS)} 个目标推送成功")
        return 0
    print("[fail] 部分/全部推送失败", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
