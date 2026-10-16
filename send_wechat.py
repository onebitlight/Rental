#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信推送统一入口（每日汇总单条推送版）

功能：
按数据源（CityExpert / HaloOglasi / 4zida）统计公寓、独栋、商铺数量，
读取 error_status.json 生成系统状态诊断文案，合并为一条微信推送消息发送。
"""

import sys
import os
import re
import subprocess
import time
from datetime import datetime
import json
import pathlib
import argparse

# ============================================================
# 微信收件人与通道配置
# ============================================================
WECHAT_TARGET = "o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat"
CHANNEL = "openclaw-weixin"
BASE_URL = "https://estate.onebitlight.xyz"

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"

# 数据源 → temp 文件映射（用于按源归类统计）
TEMP_FILE_MAP = {
    "stan_temp.json": "公寓",
    "kuca_temp.json": "独栋",
    "lokal_temp.json": "商铺",
}

# 数据源标准化名称
SOURCE_NAMES = ["CityExpert", "HaloOglasi", "4zida"]

# 错误码 → 可能原因中文说明
ERROR_REASON_HINTS = {
    "HTTP 403": "IP 被目标网站风控拦截（可能触发 Cloudflare 盾或 WAF）",
    "HTTP 429": "请求频率过高，目标站触发限流",
    "HTTP 503": "目标服务器暂时不可用",
    "HTTP 502": "目标站上游服务异常",
    "HTTP 500": "目标站内部错误",
    "Timeout": "网络超时或目标站响应过慢（可能被防火墙黑洞）",
    "ConnectionError": "网络连接失败（DNS/代理/TLS 问题）",
    "Cloudflare": "Cloudflare JS 挑战触发，cloudscraper 无法穿透",
    "ParserError": "页面结构变化，CSS 选择器/JSON 路径失效",
    "JSONDecodeError": "目标站 JSON 数据格式变化或响应不完整",
    "NoResults": "可能选择器失效或页面结构变更，未提取到有效数据",
}

# ──────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────

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


def _load_json_items(filename):
    """从 data 目录加载指定 JSON 文件，返回 items 列表。"""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return []
    try:
        data = json.loads(filepath.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data.get('items', [])
        elif isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _load_error_status():
    """加载 data/error_status.json。"""
    filepath = DATA_DIR / "error_status.json"
    if filepath.exists():
        try:
            return json.loads(filepath.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {"errors": {}, "summary": ""}


# ──────────────────────────────────────────────────────────
# 🧠 统计引擎：按数据源×房屋类型 交叉统计
# ──────────────────────────────────────────────────────────

def _build_source_stats():
    """遍历 stan/kuca/lokal_temp.json，按数据源统计各类型数量。

    返回结构:
      {
        "CityExpert": {"公寓": N, "独栋": N, "商铺": N, "total": N},
        "HaloOglasi": {"公寓": N, "独栋": N, "商铺": N, "total": N},
        "4zida":   {"公寓": N, "独栋": N, "商铺": N, "total": N},
      }
    """
    stats = {src: {"公寓": 0, "独栋": 0, "商铺": 0, "total": 0} for src in SOURCE_NAMES}

    for temp_file, house_type in TEMP_FILE_MAP.items():
        items = _load_json_items(temp_file)
        for item in items:
            source = item.get("source", "")
            # 标准化 source 名
            for known in SOURCE_NAMES:
                if known.lower() in source.lower():
                    stats[known][house_type] += 1
                    stats[known]["total"] += 1
                    break

    return stats


# ──────────────────────────────────────────────────────────
# 🩺 系统状态诊断文案生成
# ──────────────────────────────────────────────────────────

def _generate_status_text(stats: dict) -> str:
    """根据统计数据与 error_status.json 生成系统状态文案。"""
    error_data = _load_error_status()
    errors = error_data.get("errors", {})

    lines = []

    # ── 优先：有报错代码 → 展示错误 ──
    if errors:
        for src in SOURCE_NAMES:
            if src in errors:
                err = errors[src]
                code = err.get("error_code", "未知错误")
                reason = err.get("reason", "")
                # 尝试从 hints 中补充说明
                hint = ""
                for key, text in ERROR_REASON_HINTS.items():
                    if key.lower() in code.lower():
                        hint = text
                        break
                if hint:
                    lines.append(f"❌ {src}：{code} — {hint}")
                else:
                    lines.append(f"❌ {src}：{code} ({reason})")
    else:
        # ── 无报错 → 检查零抓取警告 ──
        warnings = []
        for src in SOURCE_NAMES:
            src_total = stats.get(src, {}).get("total", 0)
            if src_total == 0:
                warnings.append(f"⚠️ {src} 今日抓取为 0（可能触发 403 或选择器失效）")

        if warnings:
            lines.extend(warnings)
        else:
            lines.append("✅ 全线抓取正常（无反爬异常）")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────
# 📋 微信卡片消息构建
# ──────────────────────────────────────────────────────────

def build_daily_summary_msg(date_str=None, stan_items=None, kuca_items=None, lokal_items=None):
    """按新格式构建每日推送卡片内容。

    统计逻辑：
    1. 优先使用传入的 items 列表（用于直接传数据）
    2. 若无传入 → 从 data/*_temp.json 加载
    3. 按 data source 归类统计各类型数量
    4. 读取 error_status.json 生成系统状态
    """
    today_str = date_str or datetime.now().strftime("%Y-%m-%d")

    # ── 获取统计 ──
    if stan_items is not None and kuca_items is not None and lokal_items is not None:
        # 直接传入 → 手动构建 stats
        stats = {src: {"公寓": 0, "独栋": 0, "商铺": 0, "total": 0} for src in SOURCE_NAMES}
        for item in stan_items:
            source = item.get("source", "")
            for known in SOURCE_NAMES:
                if known.lower() in source.lower():
                    stats[known]["公寓"] += 1
                    stats[known]["total"] += 1
                    break
        for item in kuca_items:
            source = item.get("source", "")
            for known in SOURCE_NAMES:
                if known.lower() in source.lower():
                    stats[known]["独栋"] += 1
                    stats[known]["total"] += 1
                    break
        for item in lokal_items:
            source = item.get("source", "")
            for known in SOURCE_NAMES:
                if known.lower() in source.lower():
                    stats[known]["商铺"] += 1
                    stats[known]["total"] += 1
                    break
    else:
        stats = _build_source_stats()

    # ── 提取各源/型分项 ──
    ce = stats.get("CityExpert", {})
    ce_stan = ce.get("公寓", 0)
    ce_kuca = ce.get("独栋", 0)
    ce_lokal = ce.get("商铺", 0)
    ce_total = ce.get("total", 0)

    halo = stats.get("HaloOglasi", {})
    halo_stan = halo.get("公寓", 0)
    halo_kuca = halo.get("独栋", 0)
    halo_lokal = halo.get("商铺", 0)
    halo_total = halo.get("total", 0)

    zida = stats.get("4zida", {})
    zida_stan = zida.get("公寓", 0)
    zida_kuca = zida.get("独栋", 0)
    zida_lokal = zida.get("商铺", 0)
    zida_total = zida.get("total", 0)

    # ── 生成系统状态 ──
    status_text = _generate_status_text(stats)

    # ── 组装消息 ──
    msg = (
        f"🌇 【Belgrade最新房源】\n"
        f"📅 日期：{today_str}\n\n"
        f"1️⃣ CityExpert ：总数 {ce_total}\n"
        f"   公寓 {ce_stan}，独栋 {ce_kuca}，商铺 {ce_lokal}\n\n"
        f"2️⃣ HaloOglasi ：总数{halo_total}\n"
        f"   公寓 {halo_stan}，独栋 {halo_kuca}，商铺 {halo_lokal}\n\n"
        f"3️⃣ 4zida ：总数{zida_total}\n"
        f"   公寓 {zida_stan}，独栋 {zida_kuca}，商铺 {zida_lokal}\n\n"
        f"-----------------------------\n"
        f"🛠️ 系统状态：\n"
        f"{status_text}\n\n"
        f"👇 查看近期全部房源：\n"
        f"🌐 {BASE_URL}"
    )

    return msg


# ──────────────────────────────────────────────────────────
# 🚀 推送入口
# ──────────────────────────────────────────────────────────

def push_daily_summary(date_str=None, stan_items=None, kuca_items=None, lokal_items=None,
                       stan_count=None, kuca_count=None, lokal_count=None):
    """统一推送调用的主入口函数。

    支持两种调用方式：
    1. 传入 items 列表（优先）→ 交叉统计按源归类
    2. 传入 count 数字 → 使用旧版简化统计（fallback）
    """
    # ── 解析 items ──
    if stan_items is None and stan_count is not None:
        stan_items = []
    elif stan_items is None:
        stan_items = _load_json_items("stan_temp.json")

    if kuca_items is None and kuca_count is not None:
        kuca_items = []
    elif kuca_items is None:
        kuca_items = _load_json_items("kuca_temp.json")

    if lokal_items is None and lokal_count is not None:
        lokal_items = []
    elif lokal_items is None:
        lokal_items = _load_json_items("lokal_temp.json")

    msg = build_daily_summary_msg(date_str, stan_items, kuca_items, lokal_items)

    print("--- 正在向微信真实通道发送统一汇总消息 ---")
    print(msg)
    print("-----------------------------------------")

    # ── 模拟测试模式：加 --dry-run 跳过真实推送 ──
    if "--dry-run" in sys.argv:
        print("✅ [干跑模式] 消息格式已验证，未实际推送")
        return True

    out = _run_openclaw(msg)
    print("✅ 微信已真正推送")
    print("STDOUT:", out)
    return True


def push_all(text=None, items=None, house_type="kuca"):
    """兼容旧接口。"""
    count = len(items) if items is not None else 0
    if str(house_type).lower() in ["stan", "gongyu", "apartment"]:
        return push_daily_summary(stan_items=items, stan_count=count)
    elif str(house_type).lower() in ["lokal", "shop", "poslovni"]:
        return push_daily_summary(lokal_items=items, lokal_count=count)
    else:
        return push_daily_summary(kuca_items=items, kuca_count=count)


def send():
    """兼容命令行旧版调用。"""
    parser = argparse.ArgumentParser(description="微信推送脚本")
    parser.add_argument("cmd", nargs="?", default="summary", help="命令名称，默认 summary")
    parser.add_argument("--date", help="日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="模拟测试，不实际推送")
    parser.add_argument("--stan-count", type=int, help="公寓总数")
    parser.add_argument("--kuca-count", type=int, help="独栋总数")
    parser.add_argument("--lokal-count", type=int, help="商铺总数")

    args, unknown = parser.parse_known_args() if hasattr(parser, 'parse_known_args') else (parser.parse_args(), [])

    if "--dry-run" in sys.argv or args.dry_run:
        sys.argv.append("--dry-run")  # 确保透传

    if len(sys.argv) >= 2 and sys.argv[1].isdigit():
        count = int(sys.argv[1])
        h_type = sys.argv[2] if len(sys.argv) > 2 else "kuca"
        if str(h_type).lower() in ["stan", "gongyu", "apartment"]:
            push_daily_summary(stan_count=count)
        elif str(h_type).lower() in ["lokal", "shop", "poslovni"]:
            push_daily_summary(lokal_count=count)
        else:
            push_daily_summary(kuca_count=count)
        return

    push_daily_summary(
        date_str=args.date,
        stan_count=args.stan_count,
        kuca_count=args.kuca_count,
        lokal_count=args.lokal_count,
    )


if __name__ == "__main__":
    send()