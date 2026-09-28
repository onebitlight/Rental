#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信推送统一入口（修复版）

修复点：
1. 补上 scraper_stan.py 依赖的 push_all / WECHAT_TARGETS，
   避免 `from send_wechat import push_all` ImportError 后落入"只打印不发送"的哑实现。
2. 收件人 ID 统一收敛到 WECHAT_TARGETS（请确认下面的值是否是正确目标）。
3. openclaw 调用显式处理：命令缺失 / 超时 / ret=-2(Session 未激活) 都抛出真实错误，
   不再静默"成功"。
"""
import sys
import subprocess
import time

# ============================================================
# 微信收件人（⚠️ 请务必确认正确 ID）
#   PROJECT_NOTES.md 记录(用户 sgy9313): o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat
#   旧 send_wechat.py 里写的是:              o9cq806ozJVWfuJaD2MrQ8sYqFdI@im.wechat
#   两处不一致(Q0 vs Q8)，二选一确认后保留正确值，删掉另一行注释。
# ============================================================
WECHAT_TARGETS = ["o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat"]  # ← 用户 sgy9313（按文档）
# WECHAT_TARGETS = ["o9cq806ozJVWfuJaD2MrQ8sYqFdI@im.wechat"]  # ← 旧脚本里写的值

CHANNEL = "openclaw-weixin"
CHANNEL_ACCOUNT = "8c3c0f5ff3e3-im-bot"
# ⚠️ 建议把硬编码 URL 改为从 logs/guardian_state.json 动态读取，避免隧道重启后链接失效
DEFAULT_URL = "https://belgrade-rent-sgy.loca.lt"


def _run_openclaw(msg, timeout=120, retries=3, backoff=5):
    """真正触发 openclaw 微信推送。失败抛出异常，绝不静默。"""
    cmd = [
        'openclaw', 'agent',
        '--message',
        f'通过 {CHANNEL} 通道（账号 {CHANNEL_ACCOUNT}），发送给 {WECHAT_TARGETS[0]} 内容如下：\n{msg}',
    ]
    last_err = None
    for i in range(1, retries + 1):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise RuntimeError(
                "未找到 openclaw 命令：请确认 openclaw 已安装且在本机 PATH 中"
            ) from None
        except subprocess.TimeoutExpired:
            last_err = f"第{i}次超时({timeout}s)"
            time.sleep(backoff)
            continue

        out = (res.stdout or "") + (res.stderr or "")
        # 已知失败模式（PROJECT_NOTES 2026-09-24）：Session 未激活，需用户先给 bot 发条消息
        if "ret=-2" in out:
            raise RuntimeError(
                "微信 Session 未激活(ret=-2)：请先给该 bot 手动发一条消息激活，再重试"
            )
        if res.returncode == 0:
            return res.stdout
        last_err = f"第{i}次失败 rc={res.returncode}: {out.strip()[:500]}"
        time.sleep(backoff)
    raise RuntimeError(f"openclaw 推送最终失败: {last_err}")


def push_all(text=None, items=None):
    """供 scraper_stan.py 等脚本调用的微信推送入口（真正的发送，不再降级）。"""
    if items:
        lines = [text or "🏠 今日新增房源："]
        for idx, it in enumerate(items, 1):
            price = it.get('price', '面议')
            title = it.get('title', '')
            url = it.get('url', '')
            src = it.get('source', '')
            lines.append(f"{idx}. [{src}] {price}€ - {title}  {url}")
        msg = "\n".join(lines)
    else:
        msg = text or "暂无新增房源"

    out = _run_openclaw(msg)
    print("✅ 微信已推送")
    print("STDOUT:", out)
    return True


def send():
    count = sys.argv[1] if len(sys.argv) > 1 else '7'
    url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_URL
    msg = f"🏠 贝尔格莱德好房精选 ({count}套)\n\n精选纯独栋/别墅房源已更新！\n点击查看详情：\n{url}"
    print('--- 正在触发 OpenClaw 微信推送 ---')
    _run_openclaw(msg)
    print('✅ 发送完成')


if __name__ == '__main__':
    send()
#（注：内容由AI生成）
