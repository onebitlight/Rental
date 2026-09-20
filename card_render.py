#!/usr/bin/env python3
"""
Belgrade Rental — 微信推送图文卡片生成器 v2
读取 data/push_pending.json，为每个新增房源生成「左侧缩略图 + 右侧完整信息卡片」。

输出:
    data/card.html        —— 图文卡片 HTML（标题为可点击链接，标题/图片点击跳转房源 URL）
    data/card.png         —— qlmanage 渲染的整图 PNG（推送到微信）
    data/card_text.md     —— 精简文本备份（Markdown 链接标题，无裸露 HTTP 纯文本）

每套卡片字段（按需求）：
    ① 序号 + 区域中英对照（如 ① Vračar 弗拉查尔）
    €价格/月 · 面积 m² · 房数
    亮点标签（带停车位 / 独立供暖 / 全配家具 / 楼层 / 独栋等）
    街道/名称标题（可点击跳转 URL）

用法:
    python3 card_render.py            # 生成卡片(有新增则输出 PNG + 文本)
    python3 card_render.py --dry      # 只打印将收到的文本与缩略图路径，不渲染
    python3 card_render.py --html     # 只生成 HTML，不渲染 PNG
    python3 card_render.py --no-cache # 强制重新下载缩略图

依赖: requests, PIL (venv)；渲染用系统 qlmanage
"""
import argparse, datetime, json, os, re, subprocess, sys
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
PUSH_PENDING = os.path.join(DATA_DIR, "push_pending.json")
THUMBS_DIR = os.path.join(DATA_DIR, "thumbs")
CARD_HTML = os.path.join(DATA_DIR, "card.html")
CARD_PNG = os.path.join(DATA_DIR, "card.png")
CARD_TEXT = os.path.join(DATA_DIR, "card_text.md")

CARD_W = 900          # qlmanage 渲染宽度（对齐手机浏览宽度）
THUMB = 150           # 方形缩略图边长 px

HDRS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0"}

# 区域中英对照表
AREA_CN = {
    "Novi Beograd": "新贝尔格莱德", "Zemun": "泽蒙",
    "Vračar": "弗拉查尔", "Stari grad": "老城区",
    "Savski venac": "萨夫斯基维纳茨", "Čukarica": "丘卡里察",
    "Voždovac": "沃日多瓦茨", "Zvezdara": "兹韦兹达拉",
    "Palilula": "帕利卢拉", "Rakovica": "拉科维察",
    "Surčin": "苏尔钦",
}


def load_pending() -> list:
    if not os.path.exists(PUSH_PENDING):
        return []
    try:
        with open(PUSH_PENDING) as f:
            data = json.load(f)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def thumb_path(listing: dict) -> str:
    """下载并裁剪为方形缩略图，返回本地文件路径（无图/失败返回空）。"""
    photo = (listing.get("photo") or "").strip()
    if not photo:
        return ""
    os.makedirs(THUMBS_DIR, exist_ok=True)
    lid = str(listing.get("id") or listing.get("url") or "x")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", lid)[:80]
    out = os.path.join(THUMBS_DIR, safe + ".jpg")
    if os.path.exists(out):
        return out
    try:
        import requests
        from PIL import Image, ImageOps
        r = requests.get(photo, headers=HDRS, timeout=20)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        ext = ".avif" if "avif" in content_type.lower() else ".jpg"
        tmp = os.path.join(THUMBS_DIR, safe + ext)
        with open(tmp, "wb") as f:
            f.write(r.content)
        im = Image.open(tmp)
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        im = im.crop((left, top, left + side, top + side)).resize((THUMB, THUMB), Image.LANCZOS)
        im.convert("RGB").save(out, "JPEG", quality=82)
        if os.path.exists(tmp) and tmp != out:
            os.remove(tmp)
        return out
    except Exception as e:
        print(f"  [thumb] {lid}: failed ({e})", file=sys.stderr)
        return ""


def fmt_price(l: dict) -> str:
    p = l.get("price")
    return f"€{p:.0f}" if isinstance(p, (int, float)) else "€?"


def area_cn(area: str) -> str:
    """区域中英对照，如 'Vračar 弗拉查尔'。"""
    if not area:
        return ""
    a = str(area).strip()
    cn = AREA_CN.get(a)
    return f"{a} {cn}" if cn else a


def highlight_tags(l: dict) -> list:
    """根据房源特征推断亮点标签。"""
    tags = []
    # 停车位
    if l.get("parking"):
        tags.append("🅿 带停车位")
    # 供暖类型
    heating = (l.get("heating") or "").lower()
    if any(k in heating for k in ["gas", "gasno"]):
        tags.append("🔥 燃气供暖")
    if any(k in heating for k in ["central", "centralno"]):
        tags.append("🌡 集中供暖")
    if "TA" in (l.get("heating") or ""):
        tags.append("⚡ TA电暖")
    # 全配家具
    if str(l.get("furnished")) == "1":
        tags.append("🛋 全配家具")
    # 独栋
    desc = (l.get("description") or "") + (l.get("title") or "").lower()
    if "house" in desc.lower() or "独栋" in desc:
        tags.append("🏠 独栋")
    # 楼层
    floor = str(l.get("floor") or "").upper()
    floor_map = {"PR": "底层", "VPR": "顶层", "1": "1楼", "2_4": "2-4楼", "5_10": "5-10楼"}
    if floor in floor_map:
        tags.append(f"楼层 {floor_map[floor]}")
    return tags or ["📋 待看房源"]


def fmt_info(l: dict) -> str:
    parts = []
    s = l.get("size")
    if isinstance(s, (int, float)):
        parts.append(f"{s:.0f} m²")
    r = l.get("rooms")
    if isinstance(r, (int, float)):
        parts.append(f"{r:.0f} 房")
    a = area_cn(l.get("area"))
    if a:
        parts.append(a)
    return " · ".join(parts) if parts else ""


def build_html(listings: list) -> tuple:
    """返回 (html, text)。text 为 Markdown 链接标题的精简文本备份。"""
    cards = []
    lines = []
    # 中文序号：① ② ③ ④ ⑤ ...
    nums = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
    for i, l in enumerate(listings):
        thumb = thumb_path(l)
        num = nums[i] if i < len(nums) else f"{i+1}."
        street = str(l.get("street") or l.get("title") or "房源")
        url = str(l.get("url") or "")
        price = fmt_price(l)
        info = fmt_info(l)                # "80 m² · 3 房 · Surčin 苏尔钦"
        tags = highlight_tags(l)
        tags_html = "".join(f'<span class="tag">{t}</span>' for t in tags)
        areacn = area_cn(l.get("area"))   # "Surčin 苏尔钦"

        # 缩略图：有本地文件用 file://，否则留白占位
        img_html = (f'<img class="thumb" src="file://{thumb}" alt="">'
                    if thumb else '<div class="thumb ph"></div>')
        title_html = (f'<a href="{url}" target="_blank" rel="noopener">{street}</a>'
                      if url else street)

        cards.append(f"""
        <div class="card">
          <a class="thumbwrap" href="{url}" target="_blank" rel="noopener">{img_html}</a>
          <div class="body">
            <div class="area"><span class="num">{num}</span><span>{areacn}</span></div>
            <div class="ttl">{title_html}</div>
            <div class="meta"><span class="price">{price}<small>/月</small></span><span class="info">{info}</span></div>
            <div class="tags">{tags_html}</div>
          </div>
        </div>""")

        # 文本备份：标题即链接、无裸露 URL
        link = f"[{street}]({url})" if url else street
        price_short = f"{price}/月"
        info_short = re.sub(r" · [^·]*$", "", fmt_info(l))  # 去掉区域，区域单独放
        text_line = f"{num} {areacn} · {price_short} · {info_short} · {'/ '.join(tags)} · {link}"
        # 去掉标签里的 emoji 便于纯文本
        text_line = re.sub(r"[\U0001F300-\U0001FAFF]|[\u2600-\u27BF]", "", text_line)
        lines.append(text_line)

    card_body = "\n".join(cards)
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>贝尔格莱德新房源</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC','Hiragino Sans GB',sans-serif;background:#f5f6f8;padding:14px;color:#222}}
  .card{{background:#fff;border:1px solid #e7e9ee;border-radius:12px;overflow:hidden;display:flex;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  .thumbwrap{{flex:0 0 auto;text-decoration:none}}
  .thumb{{width:{THUMB}px;height:{THUMB}px;object-fit:cover;display:block}}
  .thumb.ph{{background:#eef1f6}}
  .body{{flex:1;padding:12px 14px;min-width:0}}
  .area{{font-size:13px;color:#4a5a78;margin-bottom:4px}}
  .area .num{{color:#c0392b;font-weight:700;margin-right:4px}}
  .ttl{{font-size:16px;font-weight:700;line-height:1.35;margin-bottom:6px}}
  .ttl a{{color:#1a2a4a;text-decoration:none}}
  .ttl a:hover{{text-decoration:underline;color:#2a5a9a}}
  .meta{{margin-bottom:6px}}
  .price{{font-size:20px;font-weight:800;color:#c0392b}}
  .price small{{font-size:12px;color:#999;font-weight:500}}
  .info{{font-size:13px;color:#556;margin-left:8px}}
  .tags{{display:flex;flex-wrap:wrap;gap:5px}}
  .tag{{font-size:11px;background:#eef2fa;color:#38507e;padding:2px 8px;border-radius:99px}}
</style></head><body>
{card_body}
</body></html>"""
    return html, "\n".join(lines)


def render_png(html: str) -> str:
    """用 qlmanage 把 HTML 渲染成 PNG。返回 PNG 路径或空串。"""
    html_abs = os.path.abspath(CARD_HTML)
    data_abs = os.path.abspath(DATA_DIR)
    with open(html_abs, "w") as f:
        f.write(html)
    r = subprocess.run(
        ["qlmanage", "-t", "-s", str(CARD_W), "-o", data_abs, html_abs],
        capture_output=True, text=True,
    )
    png = html_abs + ".png"
    if os.path.exists(png):
        if os.path.abspath(png) != os.path.abspath(CARD_PNG):
            os.replace(png, os.path.abspath(CARD_PNG))
        return os.path.abspath(CARD_PNG)
    print(f"  [render] qlmanage failed rc={r.returncode}:", r.stderr or r.stdout, file=sys.stderr)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    if args.no_cache:
        import shutil
        if os.path.isdir(THUMBS_DIR):
            shutil.rmtree(THUMBS_DIR)

    listings = load_pending()
    if not listings:
        print("EMPTY")
        return

    if args.dry:
        print(f"DRY listings={len(listings)}")
        for i, l in enumerate(listings):
            num = ["①","②","③","④","⑤"][i] if i < 5 else f"{i+1}."
            street = str(l.get("street") or l.get("title"))
            areacn = area_cn(l.get("area"))
            price = fmt_price(l)
            info_short = re.sub(r" · [^·]*$", "", fmt_info(l))
            tags = ", ".join(re.sub(r"[\U0001F300-\U0001FAFF]|[\u2600-\u27BF]", "", t) for t in highlight_tags(l))
            print(f"{num} {areacn} · {price}/月 · {info_short} · {tags} · {street}")
        return

    html, text = build_html(listings)
    with open(CARD_TEXT, "w") as f:
        f.write(text + "\n")

    print(f"HTML: {CARD_HTML}")
    print(f"TEXT: {CARD_TEXT}")
    if not args.html:
        png = render_png(html)
        print(f"PNG:  {png}" if png else "PNG:  (render failed)")
    print("---TEXT---")
    print(text)


if __name__ == "__main__":
    main()
