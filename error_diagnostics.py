#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
error_diagnostics.py — 跨抓取脚本共享的错误状态管理模块

提供统一的 error_status.json 读写接口，供三个爬虫脚本写入错误信息，
以及 send_wechat.py 读取并生成系统状态文案。
"""

import json
import pathlib
from datetime import datetime

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
ERROR_FILE = DATA_DIR / "error_status.json"

# 已知错误码的可能原因对照表
KNOWN_ERROR_REASONS = {
    "HTTP 403 Forbidden": "IP 被目标网站风控拦截（可能触发 Cloudflare 盾或 WAF）",
    "HTTP 429 Too Many Requests": "请求频率过高，目标站触发限流",
    "HTTP 503 Service Unavailable": "目标服务器暂时不可用",
    "HTTP 502 Bad Gateway": "目标站上游服务异常",
    "HTTP 500 Internal Server Error": "目标站内部错误",
    "Timeout": "网络超时或目标站响应过慢（可能被防火墙黑洞）",
    "ConnectionError": "网络连接失败（DNS/代理/TLS 问题）",
    "CloudflareChallengeError": "Cloudflare JS 挑战触发，cloudscraper 无法穿透",
    "ParserError": "页面结构变化，CSS 选择器/JSON 路径失效",
    "NoResults": "可能选择器失效或页面结构变更，未提取到有效数据",
    "JSONDecodeError": "目标站 JSON 数据格式变化或响应不完整",
}

# 三个数据源名称常量
SOURCE_CITYEXPERT = "CityExpert"
SOURCE_HALOOGLASI = "HaloOglasi"
SOURCE_4ZIDA = "4zida"
ALL_SOURCES = [SOURCE_CITYEXPERT, SOURCE_HALOOGLASI, SOURCE_4ZIDA]


def _classify_error(e: Exception, context: str = "") -> tuple:
    """将异常分类为统一的错误代码和可能原因。
    
    返回 (error_code, reason) 元组。reason 为 KNOWN_ERROR_REASONS 匹配项或 None。
    """
    msg = str(e)
    error_type = type(e).__name__

    # HTTP 状态码
    import re
    status_match = re.search(r'(\b403\b)', msg, re.I)
    if not status_match:
        status_match = re.search(r'(\b429\b)', msg, re.I)
    if not status_match:
        status_match = re.search(r'(\b503\b)', msg, re.I)
    if not status_match:
        status_match = re.search(r'(\b502\b)', msg, re.I)
    if not status_match:
        status_match = re.search(r'(\b500\b)', msg, re.I)
    if status_match:
        code = f"HTTP {status_match.group(1)} {msg[:80]}"
        reason = KNOWN_ERROR_REASONS.get(f"HTTP {status_match.group(1)} Forbidden") or \
                 KNOWN_ERROR_REASONS.get(f"HTTP {status_match.group(1)} Too Many Requests") or \
                 KNOWN_ERROR_REASONS.get(f"HTTP {status_match.group(1)} Service Unavailable") or \
                 None
        return (code, reason)

    # 超时
    if "timeout" in msg.lower() or "timed out" in msg.lower() or error_type == "Timeout":
        return ("Timeout", KNOWN_ERROR_REASONS.get("Timeout"))

    # 连接错误
    if "connection" in msg.lower() or error_type == "ConnectionError":
        return ("ConnectionError", KNOWN_ERROR_REASONS.get("ConnectionError"))

    # Cloudflare 相关
    if "cloudflare" in msg.lower() or "challenge" in msg.lower() or error_type == "CloudflareChallengeError":
        return ("CloudflareChallengeError", KNOWN_ERROR_REASONS.get("CloudflareChallengeError"))

    # JSON 解析错误
    if "json" in msg.lower() or error_type == "JSONDecodeError":
        return ("JSONDecodeError", KNOWN_ERROR_REASONS.get("JSONDecodeError"))

    # 通用异常 → 归类为解析错误
    return (f"{error_type}: {msg[:120]}", KNOWN_ERROR_REASONS.get("ParserError"))


def clear_source(source_name: str):
    """清除指定数据源的上一次错误记录（抓取成功后调用）。"""
    status = load_error_status()
    if source_name in status.get("errors", {}):
        del status["errors"][source_name]
        # 若无任何报错记录，清空 summary
        if not status["errors"]:
            status["summary"] = ""
        save_error_status(status)


def record_error(source_name: str, exception: Exception, context: str = ""):
    """记录一次抓取异常。
    
    Args:
        source_name: SOURCE_CITYEXPERT / SOURCE_HALOOGLASI / SOURCE_4ZIDA
        exception: 捕获到的异常对象
        context: 额外上下文（如具体函数名）
    """
    error_code, reason = _classify_error(exception, context)
    
    status = load_error_status()
    status["errors"][source_name] = {
        "error_code": error_code,
        "reason": reason or "未知原因",
        "context": context,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # 更新摘要
    if status["errors"]:
        lines = []
        for src, err in status["errors"].items():
            lines.append(
                f"{src}: {err['error_code']} ({err['reason']})"
            )
        status["summary"] = "; ".join(lines)
    else:
        status["summary"] = ""
    
    save_error_status(status)


def load_error_status() -> dict:
    """加载 error_status.json，若文件不存在则返回空结构。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ERROR_FILE.exists():
        try:
            return json.loads(ERROR_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            pass
    return {"errors": {}, "summary": ""}


def save_error_status(status: dict):
    """写入 error_status.json。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ERROR_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")