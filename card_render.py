# -*- coding: utf-8 -*-
import os, sys, json, pathlib
from datetime import datetime

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'

RENT_TYPE = sys.argv[1] if len(sys.argv) > 1 else 'stan'
DATA_FILE = DATA_DIR / 'push_pending.json' if RENT_TYPE == 'kuca' else DATA_DIR / 'new_items.json'

TODAY_STR = datetime.now().strftime('%Y-%m-%d')
EXTERNAL_RENT_DIR = pathlib.Path('/Volumes/Data2TB/rent')

OUTPUT_DIR_NAME = f"{RENT_TYPE}_{TODAY_STR}"
if EXTERNAL_RENT_DIR.exists() and os.access(EXTERNAL_RENT_DIR, os.W_OK):
    OUTPUT_DIR = EXTERNAL_RENT_DIR / OUTPUT_DIR_NAME
else:
    OUTPUT_DIR = BASE_DIR / 'output' / OUTPUT_DIR_NAME

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def extract_image_url(item):
    """兼容各种抓取字段名 (image, img, img_url, photo) 并处理 URL"""
    url = item.get('image') or item.get('img') or item.get('img_url') or item.get('photo') or ''
    if isinstance(url, list) and len(url) > 0:
        url = url[0]
    
    url = str(url).strip() if url else ''
    if url.startswith('//'):
        url = 'https:' + url
    return url

def render():
    if not DATA_FILE.exists():
        print(f"ℹ️ [{RENT_TYPE.upper()}] 未找到待渲染数据文件: {DATA_FILE}")
        return

    try:
        items = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"❌ [{RENT_TYPE.upper()}] 读取数据失败: {e}")
        return

    cards_html = ""
    for item in items:
        img_src = extract_image_url(item)
        title = item.get('title') or "贝尔格莱德精选房源"
        url = item.get('url') or "#"
        area = item.get('area_name') or item.get('location') or "贝尔格莱德"
        size = item.get('size') or item.get('area') or "未标明"
        structure = item.get('structure') or item.get('rooms') or "精选"
        price = item.get('price') or "面议"
        publisher = item.get('publisher') or "中介/机构"
        parking = item.get('parking')

        parking_badge = '<span style="background:#e6f7ff;color:#1890ff;padding:2px 6px;border-radius:4px;font-size:12px;">🅿️ 带车位</span>' if parking else ''

        # 优先使用真实抓取图片，若完全缺失则展示漂亮的图标占位
        if img_src:
            img_tag = f'<img src="{img_src}" style="width: 140px; height: 100px; object-fit: cover; border-radius: 6px; background: #f0f0f0;" alt="房源缩略图" />'
        else:
            img_tag = '<div style="width: 140px; height: 100px; border-radius: 6px; background: #f5f5f5; border: 1px dashed #d9d9d9; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#bfbfbf; font-size:12px;">🏠<span style="margin-top:4px;">暂无图片</span></div>'

        cards_html += f"""
        <div style="border: 1px solid #e8e8e8; border-radius: 8px; padding: 16px; margin-bottom: 16px; background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
            <div style="display: flex; gap: 16px;">
                {img_tag}
                <div style="flex: 1;">
                    <h3 style="margin: 0 0 8px 0; font-size: 16px;"><a href="{url}" target="_blank" style="color: #1890ff; text-decoration: none;">{title}</a></h3>
                    <p style="margin: 4px 0; color: #595959; font-size: 14px;">
                        📍 区域: <strong>{area}</strong> | 
                        📐 面积: {size} m² | 
                        🚪 房间: {structure} 间
                    </p>
                    <p style="margin: 4px 0; font-size: 18px; color: #ff4d4f; font-weight: bold;">
                        €{price} / 月
                    </p>
                    <div style="margin-top: 8px; display: flex; gap: 8px;">
                        {parking_badge}
                        <span style="background:#f6ffed;color:#52c41a;padding:2px 6px;border-radius:4px;font-size:12px;">{publisher}</span>
                    </div>
                </div>
            </div>
        </div>
        """

    type_name = "公寓 STAN" if RENT_TYPE == 'stan' else "独栋/别墅 KUCA"
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="referrer" content="no-referrer">
    <title>{type_name} 房源列表 - {TODAY_STR}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{ background: #fff; padding: 16px 24px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin:0;">🏠 贝尔格莱德 {type_name} 房源汇总 ({TODAY_STR})</h2>
            <p style="margin:8px 0 0 0; color:#8c8c8c;">共检索到 {len(items)} 套最新符合条件的房源</p>
        </div>
        {cards_html}
    </div>
</body>
</html>
"""

    out_file = OUTPUT_DIR / f'index_{TODAY_STR}.html'
    out_file.write_text(html_content, encoding='utf-8')
    print(f"🎉 [{RENT_TYPE.upper()}] 渲染完成！列表已自动生成到:\n{out_file}")

if __name__ == '__main__':
    render()
