# -*- coding: utf-8 -*-
import os, sys, json, pathlib, re
from datetime import datetime

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'

TODAY_STR = datetime.now().strftime('%Y-%m-%d')

AI_OUTPUT_ROOT = pathlib.Path(os.getenv("AI_OUTPUT_DIR", "/Volumes/Data2TB/ai_output"))
PROJECT_OUTPUT_DIR = AI_OUTPUT_ROOT / 'BelgradeEstate'
PROJECT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
            # 兼容旧目录名与新命名规范: type_date 或 type_deal_date
            m_new = re.match(r'(stan|kuca|lokal|plac)_(rent|sale)_(\d{4}-\d{2}-\d{2})', child.name)
            m_old = re.match(r'(stan|kuca|lokal)_(\d{4}-\d{2}-\d{2})', child.name)
            
            if m_new:
                house_type, deal_type, date_str = m_new.groups()
            elif m_old:
                house_type, date_str = m_old.groups()
                deal_type = 'rent' # 历史默认全部为出租
            else:
                continue

            if house_type == 'stan':
                label, emoji = '公寓', '🏢'
            elif house_type == 'kuca':
                label, emoji = '别墅', '🏡'
            elif house_type == 'lokal':
                label, emoji = '商铺', '🏪'
            else:
                label, emoji = '土地', '🌾'
            
            count = count_items_in_dir(child)
            entries.append({
                'date': date_str,
                'type': house_type,
                'deal': deal_type,
                'label': label,
                'emoji': emoji,
                'count': count,
                'href': f'./{child.name}/'
            })

    # 如果当前没有土地或出售的数据，自动生成兜底条目，确保看板结构完整
    has_plac_sale = any(e['type'] == 'plac' and e['deal'] == 'sale' for e in entries)
    if not has_plac_sale:
        entries.append({
            'date': TODAY_STR,
            'type': 'plac',
            'deal': 'sale',
            'label': '土地',
            'emoji': '🌾',
            'count': 0,
            'href': '#'
        })

    entries.sort(key=lambda e: e['date'], reverse=True)

    cards_json = json.dumps(entries, ensure_ascii=False)

    # 渲染带有 Tab 筛选与状态控制的高级交互看板
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
        .hero {{ background: rgba(255,255,255,0.95); border-radius: 16px; padding: 22px 20px; margin-bottom: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.12); text-align: center; }}
        .hero h1 {{ font-size: 24px; color: #1a1a1a; margin-bottom: 8px; }}
        .hero .subtitle {{ color: #8c8c8c; font-size: 13px; }}
        
        /* 顶部 Tab 切换栏样式 */
        .tabs {{ display: flex; background: rgba(255, 255, 255, 0.2); backdrop-filter: blur(8px); padding: 4px; border-radius: 12px; margin-bottom: 16px; gap: 4px; }}
        .tab-btn {{ flex: 1; padding: 10px; text-align: center; border-radius: 8px; font-size: 14px; font-weight: 600; color: #fff; cursor: pointer; transition: all 0.2s; border: none; background: transparent; }}
        .tab-btn.active {{ background: #fff; color: #667eea; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        
        .list {{ display: flex; flex-direction: column; gap: 12px; }}
        .card {{ background: rgba(255,255,255,0.95); border-radius: 12px; padding: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); display: flex; align-items: center; justify-content: space-between; text-decoration: none; color: inherit; transition: transform 0.15s, box-shadow 0.15s; }}
        .card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.14); }}
        
        /* 出租下土地置灰不可点击样式 */
        .card.disabled {{ background: rgba(230, 235, 245, 0.6); opacity: 0.7; cursor: not-allowed; box-shadow: none; pointer-events: none; }}
        .card.disabled:hover {{ transform: none; box-shadow: none; }}

        .card-left {{ display: flex; align-items: center; gap: 14px; }}
        .card-emoji {{ font-size: 28px; }}
        .card-info h3 {{ font-size: 15px; color: #1a1a1a; margin-bottom: 4px; }}
        .card-info .meta {{ font-size: 12px; color: #8c8c8c; }}
        .card-count {{ font-size: 22px; font-weight: 700; }}
        .card-count .num {{ color: #52c41a; }}
        .card-count .zero {{ color: #d9d9d9; }}
        .card-count .label {{ font-size: 12px; color: #8c8c8c; font-weight: 400; }}
        .footer {{ text-align: center; color: rgba(255,255,255,0.6); font-size: 12px; margin-top: 24px; }}
        .empty-tip {{ text-align: center; color: #fff; padding: 40px 0; font-size: 14px; background: rgba(255,255,255,0.1); border-radius: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="hero">
            <h1>🌇Belgrade房源看板</h1>
            <p class="subtitle">刷新时间 {now_str} </p>
        </div>

        <!-- 顶部业务类型切换 -->
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('all')">全部</button>
            <button class="tab-btn" onclick="switchTab('rent')">🔑 出租</button>
            <button class="tab-btn" onclick="switchTab('sale')">💰 出售</button>
        </div>

        <div class="list" id="card-list"></div>
        
        <div class="footer">
            Belgrade Estate Scanner · Powered by OpenClaw · {now_str}
        </div>
    </div>

<script>
    const rawEntries = {cards_json};

    function renderList(filterDeal) {{
        const container = document.getElementById('card-list');
        container.innerHTML = '';

        let filtered = rawEntries;
        if (filterDeal !== 'all') {{
            filtered = rawEntries.filter(e => e.deal === filterDeal);
        }}

        if (filtered.length === 0) {{
            container.innerHTML = '<div class="empty-tip">暂无相关房源数据，持续采集中...</div>';
            return;
        }}

        filtered.forEach(e => {{
            let isRentDisabled = (filterDeal === 'rent' && e.type === 'plac');
            let cardTag = isRentDisabled ? 'div' : 'a';
            let cardClass = 'card' + (isRentDisabled ? ' disabled' : '');
            let hrefAttr = isRentDisabled ? '' : `href="${{e.href}}"`;
            
            let countClass = e.count > 0 ? 'num' : 'zero';
            let subtitleText = isRentDisabled ? '<span style="color:#e53e3e;">- 不提供出租</span>' : `${{e.type}}_${{e.date}}`;

            let html = `
                <${{cardTag}} class="${{cardClass}}" ${{hrefAttr}}>
                    <div class="card-left">
                        <span class="card-emoji">${{e.emoji}}</span>
                        <div class="card-info">
                            <h3>${{e.label}} ${{subtitleText}}</h3>
                            <span class="meta">${{e.type}}_${{e.date}}</span>
                        </div>
                    </div>
                    <div class="card-count">
                        <span class="${{countClass}}">${{e.count}}</span>
                        <span class="label"> 套</span>
                    </div>
                </${{cardTag}}>
            `;
            container.insertAdjacentHTML('beforeend', html);
        }});
    }}

    function switchTab(deal) {{
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        event.currentTarget.classList.add('active');
        renderList(deal);
    }}

    // 初始化渲染全部
    renderList('all');
</script>
</body>
</html>
'''
    root_file.write_text(html, encoding='utf-8')
    print(f"✨ 成功生成 card_render2.py 并渲染看板！输出至: {root_file}")

if __name__ == '__main__':
    update_root_index()
