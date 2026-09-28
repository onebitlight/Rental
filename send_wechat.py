#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信推送统一入口（直连 Gateway 真实发送版）

修复点：
把 openclaw agent --message 改为 direct message send 命令行，
避免消息被发送到 AI Agent 对话框里，而是直接投递给微信 Gateway。
"""
import sys
import subprocess
import time
from datetime import datetime

# ============================================================
# 微信收件人与通道配置
# ============================================================
WECHAT_TARGET = "o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat"
CHANNEL = "openclaw-weixin"
BASE_URL = "https://estate.onebitlight.xyz"


def get_today_url(house_type="kuca"):
    """根据房源类型和当前日期动态生成完整的 H5 看板地址。"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    clean_type = str(house_type or "kuca").strip().lower()
    folder_prefix = "stan" if clean_type in ["stan", "gongyu", "apartment"] else "kuca"
    return f"{BASE_URL}/{folder_prefix}_{today_str}/index.html"


def _run_openclaw(msg, timeout=120, retries=3, backoff=5):
    """真正调用 openclaw 微信 Gateway 接口发送消息。"""
    cmd = [
        'openclaw', 'message', 'send',
        '--channel', CHANNEL,
        '--target', WECHAT_TARGET,
        '--message', msg
    ]
    last_err = None
    for i in range(1, retries + 1):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise RuntimeError("未找到 openclaw 命令：请确认 openclaw 已安装且在 PATH 中") from None
        except subprocess.TimeoutExpired:
            last_err = f"第{i}次超时({timeout}s)"
            time.sleep(backoff)
            continue

        out = (res.stdout or "") + (res.stderr or "")
        if "ret=-2" in out:
            raise RuntimeError("微信 Session 未激活(ret=-2)：请先给 bot 发条消息激活")
        if res.returncode == 0:
            return res.stdout
        
        last_err = f"第{i}次失败 rc={res.returncode}: {out.strip()[:500]}"
        time.sleep(backoff)
    raise RuntimeError(f"openclaw 推送最终失败: {last_err}")


def push_all(text=None, items=None, house_type="kuca"):
    """供 scraper 脚本调用的推送入口。"""
    if items:
        type_name = "公寓" if str(house_type).lower() in ["stan", "gongyu", "apartment"] else "独栋/别墅"
        lines = [text or f"🏠 今日新增{type_name}房源："]
        for idx, it in enumerate(items, 1):
            price = it.get('price', '面议')
            title = it.get('title', '')
            url = it.get('url', '')
            src = it.get('source', '')
            lines.append(f"{idx}. [{src}] {price}€ - {title}  {url}")
        target_url = get_today_url(house_type)
        lines.append(f"\n📊 完整 H5 看板地址：\n{target_url}")
        msg = "\n".join(lines)
    else:
        msg = text or "暂无新增房源"

    out = _run_openclaw(msg)
    print("✅ 微信已真正推送")
    print("STDOUT:", out)
    return True


def send():
    count = sys.argv[1] if len(sys.argv) > 1 else '7'
    house_type = sys.argv[2] if len(sys.argv) > 2 else 'kuca'
    
    if len(sys.argv) > 3 and sys.argv[3].startswith("http"):
        url = sys.argv[3]
    else:
        url = get_today_url(house_type)

    type_label = "精选纯独栋/别墅" if str(house_type).strip().lower() in ["kuca", "house"] else "精选公寓"
    
    msg = (
        f"🏠 贝尔格莱德好房精选 ({count}套)\n\n"
        f"{type_label}房源已更新！\n"
        f"👉 点击查看详情：\n{url}"
    )
    
    print('--- 正在向微信真实通道发送消息 ---')
    print(f'推送地址：{url}')
    _run_openclaw(msg)
    print('✅ 发送完成')


if __name__ == '__main__':
    send()
