# -*- coding: utf-8 -*-
import os, sys, json, pathlib, re
from datetime import datetime

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'

RENT_TYPE = sys.argv[1].lower() if len(sys.argv) > 1 else 'kuca'
if RENT_TYPE not in ['kuca', 'stan', 'lokal']:
    RENT_TYPE = 'kuca'

if RENT_TYPE == 'kuca':
    DATA_FILE = DATA_DIR / 'push_pending.json'
elif RENT_TYPE == 'lokal':
    DATA_FILE = DATA_DIR / 'lokal_items.json'
else:
    DATA_FILE = DATA_DIR / 'new_items.json'

TODAY_STR = datetime.now().strftime('%Y-%m-%d')

AI_OUTPUT_ROOT = pathlib.Path(os.getenv("AI_OUTPUT_DIR", "/Volumes/Data2TB/ai_output"))
PROJECT_OUTPUT_DIR = AI_OUTPUT_ROOT / 'BelgradeEstate'

OUTPUT_DIR_NAME = f"{RENT_TYPE}_{TODAY_STR}"
OUTPUT_DIR = PROJECT_OUTPUT_DIR / OUTPUT_DIR_NAME

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def count_items_in_dir(d):
    idx = d / 'index.html'
    if not idx.exists():
        return 0
    text = idx.read_text(encoding='utf-8')
    m = re.search(r'共\s*(\d+)\s*套', text)
    if m:
        return int(m.group(1))
    return 0


def update_root_index():
    root_file = PROJECT_OUTPUT_DIR / 'index.html'
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    entries = []
    if PROJECT_OUTPUT_DIR.exists():
        for child in sorted(PROJECT_OUTPUT_DIR.iterdir()):
            if not child.is_dir():
                continue
            m = re.match(r'(stan|kuca|lokal)_(\d{4}-\d{2}-\d{2})', child.name)
            if not m:
                continue
            house_type, date_str = m.groups()
            if house_type == 'stan':
                label, emoji = '公寓', '🏢'
            elif house_type == 'kuca':
                label, emoji = '别墅', '🏡'
            else:
                label, emoji = '商铺', '🏪'
            
            deal_label = '出租'
            count = count_items_in_dir(child)
            entries.append({
                'date': date_str,
                'type': house_type,
                'label': label,
                'deal_label': deal_label,
                'emoji': emoji,
                'count': count,
                'href': f'./{child.name}/'
            })

    entries.sort(key=lambda e: e['date'], reverse=True)

    cards_html = ''
    for e in entries:
        num_class = 'num' if e['count'] > 0 else 'zero'
        cards_html += f'''
            <a class="card" href="{e['href']}">
                <div class="card-left">
                    <span class="card-emoji">{e['emoji']}</span>
                    <div class="card-info">
                        <h3>{e['label']} <span style="color: #8c8c8c; font-weight: normal; font-size: 0.85em;">- {e['deal_label']}</span></h3>
                        <span class="meta">{e['type']}_{e['date']}</span>
                    </div>
                </div>
                <div class="card-count">
                    <span class="{num_class}">{e['count']}</span>
                    <span class="label"> 套</span>
                </div>
            </a>
'''

    # 🎯 总列表页面：恢复经典的深紫色渐变背景
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>贝尔格莱德房源看板</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 16px; }}
        .container {{ max-width: 700px; margin: 0 auto; width: 100%; }}
        .hero {{ background: rgba(255,255,255,0.95); border-radius: 16px; padding: 24px 20px; margin-bottom: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.12); text-align: center; }}
        .hero h1 {{ font-size: 24px; color: #1a1a1a; margin-bottom: 8px; }}
        .hero .subtitle {{ color: #8c8c8c; font-size: 13px; }}
        .list {{ display: flex; flex-direction: column; gap: 12px; }}
        .card {{ background: rgba(255,255,255,0.95); border-radius: 12px; padding: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); display: flex; align-items: center; justify-content: space-between; text-decoration: none; color: inherit; transition: transform 0.15s, box-shadow 0.15s; }}
        .card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.14); }}
        .card-left {{ display: flex; align-items: center; gap: 14px; }}
        .card-emoji {{ font-size: 28px; }}
        .card-info h3 {{ font-size: 15px; color: #1a1a1a; margin-bottom: 4px; }}
        .card-info .meta {{ font-size: 12px; color: #8c8c8c; }}
        .card-count {{ font-size: 22px; font-weight: 700; }}
        .card-count .num {{ color: #52c41a; }}
        .card-count .zero {{ color: #d9d9d9; }}
        .card-count .label {{ font-size: 12px; color: #8c8c8c; font-weight: 400; }}
        .footer {{ text-align: center; color: rgba(255,255,255,0.6); font-size: 12px; margin-top: 24px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="hero">
            <h1>🏘️ 贝尔格莱德房源</h1>
            <p class="subtitle">刷新时间 {now_str} </p>
        </div>
        <div class="list">
{cards_html}
        </div>
        <div class="footer">
            Belgrade Estate Scanner · Powered by OpenClaw · {now_str}
        </div>
    </div>
</body>
</html>
'''
    root_file.write_text(html, encoding='utf-8')


def extract_image_url(item):
    url = item.get('image') or item.get('img') or item.get('img_url') or item.get('photo') or ''
    if isinstance(url, list) and len(url) > 0:
        url = url[0]
    url = str(url).strip() if url else ''
    if url.startswith('//'):
        url = 'https:' + url
    return url

def render():
    if not DATA_FILE.exists():
        return

    try:
        raw_data = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    except Exception:
        return

    meta = {}
    if isinstance(raw_data, dict) and "items" in raw_data:
        items = raw_data.get("items", [])
        meta = raw_data.get("meta", {})
    elif isinstance(raw_data, list):
        items = raw_data
    else:
        items = []

    min_p = meta.get("min_price")
    max_p = meta.get("max_price")
    
    if min_p is not None and max_p is not None:
        price_range = f"€{min_p} - €{max_p}"
    elif items:
        prices = [float(it['price']) for it in items if isinstance(it.get('price'), (int, float))]
        if prices:
            price_range = f"€{int(min(prices))} - €{int(max(prices))}"
        else:
            price_range = "精选区间"
    else:
        price_range = "精选区间"

    cards_html = ""
    for item in items:
        img_src = extract_image_url(item)
        url = item.get('url') or "#"
        area = item.get('area_name') or item.get('area') or item.get('location') or "贝尔格莱德"
        size = item.get('size') or "未标明"
        structure_raw = item.get('structure') or item.get('rooms')
        structure = structure_raw if structure_raw is not None else "精选"
        price = item.get('price') or "面议"
        publisher = item.get('publisher') or "中介"
        parking = item.get('parking')

        parking_badge = '<span style="background:#ebf8ff;color:#3182ce;padding:2px 6px;border-radius:4px;font-size:11px;">🅿️ 带车位</span>' if parking else ''
        is_street_level = item.get('is_street_level')
        street_badge = '<span style="background:#fffaf0;color:#dd6b20;padding:2px 6px;border-radius:4px;font-size:11px;">🏪 临街</span>' if is_street_level else ''

        if img_src:
            img_tag = f'<img src="{img_src}" style="width: 160px; height: 120px; object-fit: cover; border-radius: 6px; background: #edf2f7; display: block;" alt="房源缩略图" />'
        else:
            img_tag = '<div style="width: 160px; height: 120px; border-radius: 6px; background: #f7fafc; border: 1px dashed #cbd5e0; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#a0aec0; font-size:12px;">🏠<span style="margin-top:4px;">暂无图片</span></div>'

        cards_html += f"""
        <div style="border: 1px solid rgba(255,255,255,0.6); border-radius: 12px; padding: 14px; margin-bottom: 14px; background: rgba(255,255,255,0.85); backdrop-filter: blur(10px); box-shadow: 0 4px 16px rgba(100,150,220,0.08);">
            <div style="display: flex; gap: 14px; align-items: flex-start;">
                <!-- 左侧：图片 + 下方固定中文“点击查看详情”链接 -->
                <div style="flex-shrink: 0; width: 160px;">
                    <a href="{url}" target="_blank" style="text-decoration: none; display: block; width: 160px; height: 120px;">
                        {img_tag}
                    </a>
                    <div style="margin-top: 6px; font-size: 13px; font-weight: 600; line-height: 1.3; text-align: center;">
                        <a href="{url}" target="_blank" style="color: #3182ce; text-decoration: none;">点击查看详情</a>
                    </div>
                </div>
                <!-- 右侧：行政区保持在右侧，以及面积、价格、标签等 -->
                <div style="flex: 1; min-width: 0;">
                    <p style="margin: 0 0 7px 0; color: #4a5568; font-size: 15px;">
                        📍 : {area} <br> 
                        📐 : {size} m²{(' <br> 🚪 : ' + str(structure) + ' 间') if structure_raw is not None and RENT_TYPE != 'lokal' else ''}
                    </p>
                    <p style="margin: 6px 0; font-size: 18px; color: #e53e3e; font-weight: bold;">
                        €{price} / 月
                    </p>
                    <div style="margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap;">
                        {parking_badge}
                        {street_badge}
                        <span style="background:#f0fff4;color:#38a169;padding:2px 6px;border-radius:4px;font-size:11px;">{publisher}</span>
                    </div>
                </div>
            </div>
        </div>
        """

    if RENT_TYPE == 'stan':
        type_name = "公寓"
    elif RENT_TYPE == 'kuca':
        type_name = "别墅"
    else:
        type_name = "商铺"

    # 🎯 各业态详情页：保持清爽高档的浅蓝色渐变背景
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="referrer" content="no-referrer">
    <title>{type_name} 房源列表 - {TODAY_STR}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: radial-gradient(circle at 50% 30%, #f0f6ff 0%, #e2eeff 50%, #d4e6ff 100%); margin: 0; padding: 12px; min-height: 100vh; color: #2d3748; }}
        .container {{ max-width: 100%; width: 100%; margin: 0 auto; }}
        .header {{ background: rgba(255,255,255,0.85); backdrop-filter: blur(10px); padding: 16px 20px; border-radius: 14px; margin-bottom: 16px; box-shadow: 0 8px 32px rgba(100,150,220,0.12); border: 1px solid rgba(255,255,255,0.6); }}
        .footer {{ text-align: center; color: rgba(113,128,150,0.8); font-size: 12px; margin-top: 24px; }}
        @media (min-width: 768px) {{
            .container {{ max-width: 750px; }}
            body {{ padding: 24px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin:0; font-size: 20px; color: #1a202c;">🏠 贝尔格莱德{type_name}房源汇总 ({TODAY_STR})</h2>
            <p style="margin:6px 0 0 0; color:#718096; font-size: 13px;">检索范围：{price_range}，共 {len(items)} 套</p>
        </div>
        {cards_html}
        <div class="footer">
            Belgrade Estate Scanner · Powered by OpenClaw · {TODAY_STR}
        </div>
    </div>
</body>
</html>
"""

    out_file = OUTPUT_DIR / 'index.html'
    out_file.write_text(html_content, encoding='utf-8')
    update_root_index()
    print(f"✨ 成功生成 card_render_v2.py 并渲染！总索引页已恢复经典深紫渐变，业态页保持浅蓝渐变。输出至: {out_file}")

if __name__ == '__main__':
    render()
