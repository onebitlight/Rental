# -*- coding: utf-8 -*-
"""
detail_render.py — 规范化中文房源详情页 HTML 渲染（通用版）

结构（对齐需求）：
  1. 页头：房屋标题、价格、个人/中介身份标签、主图
  2. 核心参数网格（Grid）：面积 | 户型 | 楼层 | 供暖
  3. 详细属性标签列表：家具 | 车位 | 电梯 | 阳台 | 储藏 | 宠物/政策
  4. 中文 AI 智能解析框：AI 提炼亮点 + 起租/押金须知
  5. 原始描述中文大意（可折叠）
  6. 页脚：直达原网链接按钮

输入：detail dict（由 detail_scraper.scrape_detail + ai_analyze.analyze 产出）
输出：完整 HTML 字符串。
"""


def _esc(v):
    if v is None:
        return ''
    s = str(v)
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;'))


def _core_grid_items(detail, analysis):
    """核心参数网格：面积/户型/楼层/供暖（取 AI 标准化值或兜底值）。"""
    std = (analysis or {}).get('std_attrs') or {}
    core = detail.get('core') or {}
    grid = []
    grid.append(('面积', std.get('面积') or core.get('面积') or '—'))
    grid.append(('户型', std.get('户型') or core.get('户型') or '—'))
    grid.append(('楼层', std.get('楼层') or core.get('楼层') or '—'))
    grid.append(('供暖', std.get('供暖') or core.get('供暖') or '未说明'))
    return grid


def _amenity_tags(detail, analysis):
    """标签列表：家具 | 车位 | 电梯 | 阳台 | 储藏 | 宠物政策等。"""
    std = (analysis or {}).get('std_attrs') or {}
    detail_std = detail.get('std_attrs') or {}
    tags = []
    # 家具状态
    furn = std.get('家具状态') or detail_std.get('家具状态') or (detail.get('core') or {}).get('家具状态')
    if furn:
        tags.append(furn)
    # 配套
    amenity_map = {'车位': '🅿️ 车位', '电梯': '🛗 电梯', '阳台': '🏞️ 阳台',
                   '地下室/储藏室': '📦 储藏室', '储藏室': '📦 储藏室',
                   '空调': '❄️ 空调', '网络': '🌐 网络', '装修状态': '🛠️ 装修'}
    for k, label in amenity_map.items():
        v = std.get(k) or detail_std.get(k)
        if v:
            tags.append(f"{label}{'' if v in ('有', '是') else '·' + _esc(v)}")
    # 装修状态（若还没以标签列出）
    cond = std.get('装修状态') or detail_std.get('装修状态')
    if cond and not any('装修' in t for t in tags):
        tags.append(f"🛠️ {_esc(cond)}")
    # 政策（宠物/押金/租期）
    policy = (analysis or {}).get('policy') or [p for p in (detail.get('policy') or []) if p]
    if policy:
        for p in policy[:4]:
            tags.append(f"📋 {_esc(p)}")
    # 配套兜底（detail amenities 中非政策类、未列出的项）
    policy_set = set(policy)
    for a in detail.get('amenities') or []:
        if a in policy_set or any(a in t for t in tags):
            continue
        tags.append(f"✨ {_esc(a)}")
    # 去重
    seen = set()
    uniq = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def render_detail_html(detail, analysis, today_str, back_link=None, ai_badge=True):
    """渲染单套房源的规范化中文详情页 HTML。"""
    std = (analysis or {}).get('std_attrs') or {}
    grid = _core_grid_items(detail, analysis)
    tags = _amenity_tags(detail, analysis)
    highlights = (analysis or {}).get('highlights') or '该房源已通过预算筛选，详见原网。'
    policy_notes = (analysis or {}).get('policy') or detail.get('policy') or []
    desc = detail.get('description') or ''
    image = detail.get('image') or ''
    price = detail.get('price')
    price_str = f"€{price}" if price else '价格见原网'
    publisher = detail.get('publisher') or '中介/机构'
    pclass = 'personal' if publisher == '个人' else 'agency'
    source = detail.get('source') or '原平台'
    url = detail.get('url') or ''
    title = detail.get('title') or '贝尔格莱德房源'
    ai_label = 'AI 智能解析' if ai_badge and (analysis or {}).get('ai') else '智能解析(规则兜底)' if ai_badge else '房源解析'

    # 政策须知行
    policy_line = '、'.join(policy_notes) if policy_notes else '以原网页实际条款为准'

    # 渲染参数网格
    grid_html = ''.join(
        f'<div class="gitem"><div class="gv">{_esc(v)}</div><div class="gl">{_esc(k)}</div></div>'
        for k, v in grid)

    # 标签
    tags_html = ''.join(f'<span class="tag">{t}</span>' for t in tags) if tags else \
        '<span class="muted">信息以原网为准</span>'

    # 描述折叠（中文大意：展示原文，可折叠）
    desc_html = ''
    if desc:
        desc_html = f'''
      <details class="fold">
        <summary>📄 原始描述（点击展开原文大意）</summary>
        <div class="foldbody">{_esc(desc)}</div>
      </details>
'''

    back = back_link or f'../index_{today_str}.html'

    return f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} - 贝尔格莱德中文看房</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,"PingFang SC","Segoe UI",Roboto,sans-serif;background:#0e1a2b;color:#f2f5f9;padding:20px}}
  .wrap{{max-width:760px;margin:0 auto}}
  a.back{{display:inline-block;color:#9fb8e8;font-size:13px;margin-bottom:14px;text-decoration:none}}
  a.back:hover{{text-decoration:underline}}
  .card{{background:#ffffff;color:#1f2a3d;border-radius:16px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.35);margin-bottom:18px}}
  .pic{{height:340px;background:#e4e8f0 center/cover no-repeat}}
  .body{{padding:24px}}
  .top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:8px;flex-wrap:wrap}}
  .price{{font-size:34px;font-weight:800;color:#c0392b}}
  .price small{{font-size:14px;color:#888;font-weight:500}}
  .right{{display:flex;gap:6px;align-items:center}}
  .publisher{{font-size:13px;padding:5px 13px;border-radius:99px;font-weight:600}}
  .publisher.personal{{background:#e8f6ec;color:#1e7d3c}}
  .publisher.agency{{background:#eef2fa;color:#38507e}}
  .src{{font-size:12px;background:#eef2fa;color:#38507e;padding:4px 10px;border-radius:99px;font-weight:600}}
  h1{{font-size:22px;margin-bottom:6px;color:#1f2a3d;line-height:1.4}}
  .street{{font-size:13px;color:#889;margin-bottom:18px}}

  .stitle{{font-size:15px;font-weight:700;color:#27437f;margin:22px 0 10px;border-left:4px solid #27437f;padding-left:8px}}

  /* 核心参数网格 */
  .grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
  @media(min-width:520px){{.grid{{grid-template-columns:repeat(4,1fr)}}}}
  .gitem{{background:#f4f6fb;border:1px solid #e6ebf5;border-radius:12px;padding:14px 12px;text-align:center}}
  .gv{{font-size:17px;font-weight:800;color:#1f2a3d}}
  .gl{{font-size:12px;color:#7d8aa5;margin-top:4px}}

  /* 标签 */
  .tags{{display:flex;flex-wrap:wrap;gap:8px}}
  .tag{{background:#eef2fa;color:#38507e;border:1px solid #dbe3f2;font-size:13px;padding:6px 13px;border-radius:99px;font-weight:600}}
  .tag.alt{{background:#fff6e8;color:#b06a00;border-color:#f0ddb8}}

  /* AI 解析框 */
  .ai{{background:linear-gradient(135deg,#1a2a4a,#27437f);border-radius:14px;padding:20px 22px;color:#eaf0ff}}
  .ai .hh{{font-size:13px;letter-spacing:1px;color:#9fb8e8;font-weight:700;margin-bottom:10px;display:flex;align-items:center;gap:6px}}
  .ai p{{font-size:14.5px;line-height:1.85;color:#f2f6ff}}
  .ai .note{{margin-top:14px;font-size:13px;color:#c6d4f5;border-top:1px solid #3a548f;padding-top:12px}}
  .ai .note b{{color:#ffd479}}

  .muted{{color:#9aa7bd;font-size:13px}}

  /* 折叠 */
  details.fold{{background:#f8f9fc;border:1px solid #e6ebf5;border-radius:10px;padding:12px 14px;margin-bottom:8px}}
  details.fold summary{{cursor:pointer;font-size:14px;font-weight:600;color:#27437f}}
  details.fold .foldbody{{font-size:13px;color:#444;line-height:1.8;margin-top:10px;border-top:1px dashed #dbe3f2;padding-top:10px;white-space:pre-wrap}}

  /* 原网按钮 */
  .btn{{display:block;text-align:center;background:linear-gradient(135deg,#27437f,#1a2a4a);color:#fff;padding:15px;border-radius:12px;font-size:16px;font-weight:bold;text-decoration:none;margin-top:8px;box-shadow:0 4px 12px rgba(39,67,127,.3)}}
  .btn:hover{{filter:brightness(1.1)}}
  footer{{text-align:center;color:#6b7f9e;font-size:12px;padding:14px 0}}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="{_esc(back)}">← 返回今日房源列表</a>
  <div class="card">
    <div class="pic" style="background-image:url('{_esc(image)}')"></div>
    <div class="body">
      <div class="top">
        <span class="price">{_esc(price_str)}<small>/月</small></span>
        <div class="right">
          <span class="publisher {pclass}">{_esc(publisher)}</span>
          <span class="src">{_esc(source)}</span>
        </div>
      </div>
      <h1>{_esc(title)}</h1>
      <div class="street">📍 塞尔维亚 · 贝尔格莱德</div>

      <div class="stitle">核心参数</div>
      <div class="grid">
        {grid_html}
      </div>

      <div class="stitle">房屋亮点与配置</div>
      <div class="tags">
        {tags_html}
      </div>

      <div class="stitle">{ai_label}</div>
      <div class="ai">
        <div class="hh">🤖 AI 中文提炼</div>
        <p>{_esc(highlights)}</p>
        <div class="note">
          <b>起租 / 押金须知：</b>{_esc(policy_line)}<br>
          <span style="font-size:12px;color:#9fb8e8">信息由 AI 基于原网页提取，请以原平台实际条款为准。</span>
        </div>
      </div>

      {desc_html}

      <a class="btn" href="{_esc(url)}" target="_blank" rel="noopener">🌐 在原平台（{_esc(source)}）查看完整房源与地图</a>
    </div>
  </div>
  <footer>贝尔格莱德租房智能监控 · 华人专属中文看板</footer>
</div>
</body>
</html>
'''
