#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信推送统一入口（每日汇总单条推送版）

功能：
将公寓 (Stan)、独栋 (Kuća) 和商铺 (Lokal) 的新增数量、价格区间及对应看板链接合并为一条微信推送消息发送。
"""

import sys
import os
import re
import subprocess
import time
from datetime import datetime
import argparse

# ============================================================
# 微信收件人与通道配置
# ============================================================
WECHAT_TARGET = "o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat"
CHANNEL = "openclaw-weixin"
BASE_URL = "https://estate.onebitlight.xyz"

# 预设检索价格区间（与各 scraper 中的 MIN_PRICE/MAX_PRICE 保持一致）
# 当当天无新增房源时，fallback 显示此预设区间而非"暂无价格信息"
PRESET_PRICE_RANGE = {
    'stan': (350, 650),
    'kuca': (500, 1300),
    'lokal': (400, 2000),
}


def get_today_url(house_type="kuca", date_str=None):
    """根据房源类型和日期动态生成完整的 H5 看板地址。"""
    today_str = date_str or datetime.now().strftime("%Y-%m-%d")
    clean_type = str(house_type or "kuca").strip().lower()
    if clean_type in ["stan", "gongyu", "apartment"]:
        folder_prefix = "stan"
    elif clean_type in ["lokal", "shop", "poslovni"]:
        folder_prefix = "lokal"
    else:
        folder_prefix = "kuca"
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


def extract_price_range(items):
    """从房源列表数据中自动解析计算最低和最高价格。"""
    if not items:
        return None, None
    prices = []
    for item in items:
        if not isinstance(item, dict):
            continue
        p = item.get('price') or item.get('price_eur') or ''
        nums = re.findall(r'\d+(?:[\.,]\d+)?', str(p).replace(' ', ''))
        for num_str in nums:
            try:
                val = float(num_str.replace(',', '.'))
                if val > 50:
                    prices.append(val)
            except ValueError:
                continue
    if not prices:
        return None, None
    min_p, max_p = min(prices), max(prices)
    return int(min_p) if min_p.is_integer() else round(min_p, 1), int(max_p) if max_p.is_integer() else round(max_p, 1)


def format_price_range(min_p, max_p, house_type=None):
    """格式化价格区间显示字符串。
    优先级：实际数据 > 预设检索区间 > 暂无价格信息。
    """
    if min_p is not None and max_p is not None:
        if min_p == max_p:
            return f"{int(min_p):,}€/月"
        return f"{int(min_p):,}€ - {int(max_p):,}€/月"
    elif min_p is not None:
        return f"约 {int(min_p):,}€/月起"

    if house_type and house_type in PRESET_PRICE_RANGE:
        lo, hi = PRESET_PRICE_RANGE[house_type]
        return f"{lo:,}€ - {hi:,}€/月"
    return "暂无价格信息"


def build_daily_summary_msg(date_str=None, stan_info=None, kuca_info=None, lokal_info=None):
    """构建统一格式的每日推送文本。"""
    today_str = date_str or datetime.now().strftime("%Y-%m-%d")
    
    stan_info = stan_info or {}
    kuca_info = kuca_info or {}
    lokal_info = lokal_info or {}
    
    stan_count = stan_info.get('count', 0)
    stan_price_str = stan_info.get('price_str') or format_price_range(stan_info.get('min_price'), stan_info.get('max_price'))
    stan_url = stan_info.get('url') or get_today_url('stan', today_str)

    kuca_count = kuca_info.get('count', 0)
    kuca_price_str = kuca_info.get('price_str') or format_price_range(kuca_info.get('min_price'), kuca_info.get('max_price'))
    kuca_url = kuca_info.get('url') or get_today_url('kuca', today_str)

    lokal_count = lokal_info.get('count', 0)
    lokal_price_str = lokal_info.get('price_str') or format_price_range(lokal_info.get('min_price'), lokal_info.get('max_price'))
    lokal_url = lokal_info.get('url') or get_today_url('lokal', today_str)

    msg_parts = [
        f"🌇 【Belgrade房源推送】\n"
        f"📅  日期：{today_str}\n\n"
        f"🏢 公寓 (Stan)：新增 {stan_count} 套\n"
        f"💰 价格：{stan_price_str}\n"
        f"🌐 看板：{stan_url}\n\n"
        f"🏡 独栋 (Kuća)：新增 {kuca_count} 套\n"
        f"💰 价格：{kuca_price_str}\n"
        f"🌐 看板：{kuca_url}\n\n"
        f"🏪 商铺 (Lokal)：新增 {lokal_count} 套\n"
        f"💰 价格：{lokal_price_str}\n"
        f"🌐 看板：{lokal_url}\n\n"
        f"👇 查看近期全部房源：\n"
        f"🌐 列表：{BASE_URL}"
    ]
    return ''.join(msg_parts)


def push_daily_summary(date_str=None, stan_items=None, kuca_items=None, lokal_items=None,
                       stan_count=None, stan_min=None, stan_max=None,
                       kuca_count=None, kuca_min=None, kuca_max=None,
                       lokal_count=None, lokal_min=None, lokal_max=None):
    """统一推送调用的主入口函数。"""
    s_count = len(stan_items) if stan_items is not None else (stan_count or 0)
    s_min, s_max = (None, None)
    if stan_items:
        s_min, s_max = extract_price_range(stan_items)
    s_min = stan_min if stan_min is not None else s_min
    s_max = stan_max if stan_max is not None else s_max
    
    stan_info = {
        'count': s_count,
        'min_price': s_min,
        'max_price': s_max,
        'price_str': format_price_range(s_min, s_max, 'stan'),
        'url': get_today_url('stan', date_str)
    }

    k_count = len(kuca_items) if kuca_items is not None else (kuca_count or 0)
    k_min, k_max = (None, None)
    if kuca_items:
        k_min, k_max = extract_price_range(kuca_items)
    k_min = kuca_min if kuca_min is not None else k_min
    k_max = kuca_max if kuca_max is not None else k_max

    kuca_info = {
        'count': k_count,
        'min_price': k_min,
        'max_price': k_max,
        'price_str': format_price_range(k_min, k_max, 'kuca'),
        'url': get_today_url('kuca', date_str)
    }

    l_count = len(lokal_items) if lokal_items is not None else (lokal_count or 0)
    l_min, l_max = (None, None)
    if lokal_items:
        l_min, l_max = extract_price_range(lokal_items)
    l_min = lokal_min if lokal_min is not None else l_min
    l_max = lokal_max if lokal_max is not None else l_max

    lokal_info = {
        'count': l_count,
        'min_price': l_min,
        'max_price': l_max,
        'price_str': format_price_range(l_min, l_max, 'lokal'),
        'url': get_today_url('lokal', date_str)
    }

    msg = build_daily_summary_msg(date_str, stan_info, kuca_info, lokal_info)

    print('--- 正在向微信真实通道发送统一汇总消息 ---')
    print(msg)
    print('-----------------------------------------')
    out = _run_openclaw(msg)
    print('✅ 微信已真正推送')
    print("STDOUT:", out)
    return True


def push_all(text=None, items=None, house_type="kuca"):
    """兼容旧接口：单类型推送到每日汇总格式。"""
    count = len(items) if items else 0
    min_p, max_p = extract_price_range(items) if items else (None, None)
    
    if str(house_type).lower() in ["stan", "gongyu", "apartment"]:
        return push_daily_summary(stan_items=items, stan_count=count, stan_min=min_p, stan_max=max_p)
    else:
        return push_daily_summary(kuca_items=items, kuca_count=count, kuca_min=min_p, kuca_max=max_p)


def send():
    """兼容命令行旧版调用。"""
    parser = argparse.ArgumentParser(description="微信推送脚本")
    parser.add_argument("cmd", nargs="?", default="summary", help="命令名称，默认 summary")
    parser.add_argument("--date", help="日期 YYYY-MM-DD")
    parser.add_argument("--stan-count", type=int, default=0, help="公寓新增数量")
    parser.add_argument("--stan-min", type=float, help="公寓最低价")
    parser.add_argument("--stan-max", type=float, help="公寓最高价")
    parser.add_argument("--kuca-count", type=int, default=0, help="独栋新增数量")
    parser.add_argument("--kuca-min", type=float, help="独栋最低价")
    parser.add_argument("--kuca-max", type=float, help="独栋最高价")
    parser.add_argument("--lokal-count", type=int, default=0, help="商铺新增数量")
    parser.add_argument("--lokal-min", type=float, help="商铺最低价")
    parser.add_argument("--lokal-max", type=float, help="商铺最高价")
    
    args, unknown = parser.parse_known_args() if hasattr(parser, 'parse_known_args') else (parser.parse_args(), [])

    if len(sys.argv) >= 2 and sys.argv[1].isdigit():
        count = int(sys.argv[1])
        h_type = sys.argv[2] if len(sys.argv) > 2 else 'kuca'
        if str(h_type).lower() in ['stan', 'gongyu', 'apartment']:
            push_daily_summary(stan_count=count)
        else:
            push_daily_summary(kuca_count=count)
        return

    push_daily_summary(
        date_str=args.date,
        stan_count=args.stan_count,
        stan_min=args.stan_min,
        stan_max=args.stan_max,
        kuca_count=args.kuca_count,
        kuca_min=args.kuca_min,
        kuca_max=args.kuca_max,
        lokal_count=args.lokal_count,
        lokal_min=args.lokal_min,
        lokal_max=args.lokal_max
    )


if __name__ == '__main__':
    send()
