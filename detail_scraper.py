# -*- coding: utf-8 -*-
"""
detail_scraper.py — 通用塞尔维亚房源详情页深度抓取（不绑定单一网站）

设计目标：适配 HaloOglasi / CityExpert / Nekretnine 及任意主流房源网。
做法不是为每个网站写一套选择器，而是：
  1. 尽量收集页面里的「结构化信号源」：
       - <meta> og:* / description / keywords
       - JSON-LD (<script type="application/ld+json">)
       - 可见表格/键值对（<li>、<dt>/<dd>、<th>/<td>、label:value 文本）
  2. 对整页可见文本做「塞尔维亚语/英语关键词」扫描，兜底识别 4 类信息：
       核心字段(价格/面积/户型/楼层/供暖/家具/发布者) / 配套(车位/电梯/阳台/储藏/空调/网络)
       政策(宠物/押金/最短租期/起租) / 原始正文描述
  3. 返回统一 dict：{ raw_text, attrs{native_name:value}, description, image,
                       core{价格,面积,户型,楼层,供暖,家具,装修,发布者},
                       amenities[..], policy[..] }

由调用方（scraper.py）在拿到合格房源 URL 后，逐个打开详情页调用本模块。
"""

import re, json
from html import unescape

# ---------- 塞尔维亚语 / 英文 关键词表 ----------

# 属性「原生名 → (标准中文键, 取值提取优先级)」 用于把任意键值对字段映射到标准中文键
_ATTR_FIELD_MAP = {
    # 面积
    'kvadratura': ('面积', 'v'), 'povrsina': ('面积', 'v'), 'površina': ('面积', 'v'),
    'korisna površina': ('面积', 'v'), 'ukupna površina': ('面积', 'v'),
    'area': ('面积', 'v'), 'size': ('面积', 'v'),
    # 户型/房间数
    'broj soba': ('户型', 'v'), 'soba': ('户型', 'v'), 'rooms': ('户型', 'v'),
    'ukupno soba': ('户型', 'v'), 'broj spavaćih soba': ('户型', 'v'),
    # 楼层
    'spratnost': ('楼层', 'v'), 'sprat': ('楼层', 'v'), 'floor': ('楼层', 'v'),
    'ukupan broj spratova': ('总楼层', 'v'),
    # 供暖
    'grejanje': ('供暖', 'm'), 'grejno telo': ('供暖', 'v'), 'heating': ('供暖', 'm'),
    # 家具
    'namesten': ('家具状态', 'm'), 'namešten': ('家具状态', 'm'), 'opremljenost': ('家具状态', 'm'),
    'furnished': ('家具状态', 'm'), 'mobiliran': ('家具状态', 'm'),
    # 装修/状态
    'stanje': ('装修状态', 'm'), 'condition': ('装修状态', 'm'),
    # 车位
    'parking': ('车位', 'm'), 'garaza': ('车位', 'm'), 'garaža': ('车位', 'm'),
    'parking mesto': ('车位', 'm'),
    # 电梯
    'lift': ('电梯', 'm'), 'elevator': ('电梯', 'm'),
    # 阳台
    'terasa': ('阳台', 'm'), 'terace': ('阳台', 'm'), 'balkon': ('阳台', 'm'),
    # 储藏
    'podrum': ('地下室/储藏室', 'm'), 'ostava': ('地下室/储藏室', 'm'),
    # 空调/网络
    'klima': ('空调', 'm'), 'internet': ('网络', 'm'),
    # 价格
    'cena': ('价格', 'v'), 'price': ('价格', 'v'),
    'ukupna cena': ('价格', 'v'), 'mesecna zakupnina': ('价格', 'v'),
    # 发布者
    'oglasivac': ('发布者', 'v'), 'prodavac': ('发布者', 'v'),
    'agencija': ('发布者', 'm'), 'vlasnik': ('发布者', 'm'),
    # 朝向/年份/能源
    'orijentacija': ('朝向', 'v'), 'orientacija': ('朝向', 'v'),
    'godina izgradnje': ('建筑年份', 'v'), 'year of construction': ('建筑年份', 'v'),
    'energetski razred': ('能源等级', 'm'), 'energy class': ('能源等级', 'm'),
    'vlasnistvo': ('产权', 'm'),
}

# 布尔型「有/无」配套（出现即代表有该项）
_AMENITY_KEYS = {
    'parking': '车位', 'garaza': '车位', 'garaža': '车位', 'lift': '电梯',
    'terasa': '阳台', 'terace': '阳台', 'balkon': '阳台', 'podrum': '地下室/储藏室',
    'ostava': '储藏室', 'klima': '空调', 'internet': '网络',
}

# 供热类型 → 标准中文（映射"CG"等原生缩写）
_HEAT_VALUE_MAP = [
    (r'centralno|central|city heating|daljinsko|CG\b', '集中供暖'),
    (r'gasno|gas\b|gasni', '燃气供暖'),
    (r'elektric|električno|struja|electric', '电暖'),
    (r'podno|floor heating', '地暖'),
    (r'ta\b|ta peć|etažno', '分户供暖'),
    (r'na ugalj|kombinovano', '燃煤/混合供暖'),
]

# 家具状态值映射
_FURN_VALUE_MAP = [
    (r'prazan|bez namest|bez namešt', '未配家具'),
    (r'polu|delimicno|delimično|partially', '半配家具'),
    (r'kompletno|namešten|namesten|fully|furnished', '全配家具'),
]
_FURN_POSITIVE = re.compile(r'namest|namešten|opremljen|mobiliran|furnish', re.I)

# 原文正文描述的可能容器（通用类名/标签；尽量宽松，能命中几个算几个）
# 优先级从高到低：og:description/meta description（HaloOglasi 等站点即使正文被 cookie 遮挡，
# 也会在 meta 里带完整真实中文/塞语描述）> JSON-LD > 页面正文容器。
_DESC_SELECTORS = [
    'meta[property="og:description"]',
    'meta[name="description"]',
    'div[itemprop="description"]',
    'div[class*=description]', 'div[class*=opis]', 'div[class*=about]',
    'div[class*=tekst]', 'article p', '.description', '.opis',
]

# 政策关键词
_PET_POS = re.compile(r'dozvoljeni? ljubimci|mogući? ljubimci|pet friendly|ljubimci dozvoljeni|允许养|可养宠物', re.I)
_PET_NEG = re.compile(r'bez ljubimaca|bez kućnih|no pets|no pet|ne dozvoljava se|禁宠|不允许养宠物', re.I)
_DEPOSIT = re.compile(r'depozit|kaucija|deposit|押金|押[一二]付', re.I)
_LEASE_MIN = re.compile(r'minimum[^,.;]{0,20}|minimalno[^,.;]{0,20}|najmanje[^,.;]{0,20}|最短租期[^,；。]{0,20}|最少[^,，。]{0,10}个月', re.I)
_MOVEIN = re.compile(r'useljiv|useljenje|odmah useljiv|move[- ]in|起租|入住', re.I)
_LEASE_TERM = re.compile(r'(?:ugovor|period|rok)[^,.;]{0,30}|(?:租期|合约)[^,，。]{0,20}', re.I)

# 发布者身份
_AGENCY_WORDS = re.compile(r'agencija|agency|firma|kompanija|pravno lice|中介|机构', re.I)
_OWNER_WORDS = re.compile(r'vlasnik|owner|individ|fizičko lice|fizicko|个人|房东直租', re.I)


def _clean(text):
    """清洗文本：去 HTML 实体、空白折叠、去空行。"""
    if not text:
        return ""
    t = unescape(str(text))
    t = t.replace('\xa0', ' ').replace('\u200b', '')
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n', t)
    return t.strip()


def _extract_jsonld(page):
    """收集页面所有 JSON-LD 块，拍平为若干结构化条目。返回 [dict, ...]。"""
    out = []
    try:
        for script in page.query_selector_all('script[type="application/ld+json"]'):
            txt = script.inner_text() if script else ''
            txt = _clean(txt)
            if not txt:
                continue
            try:
                data = json.loads(txt)
            except Exception:
                continue
            # 拍平 @graph / 列表
            if isinstance(data, dict) and data.get('@graph'):
                data = data['@graph']
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict):
                    out.append(it)
    except Exception:
        pass
    return out


def _collect_keyvalues(page):
    """从可见 DOM 收集「原生字段名 → 值」键值对（多站点通用）。"""
    pairs = {}
    try:
        # 常见键值容器：<li>label:value、<dt>/<dd>、<th>/<td>
        for li in page.query_selector_all('ul[class*="feature"] li, ul[class*="feature"] div, '
                                          'div[class*="feature"] li, li[class*="feature"]'):
            txt = _clean(li.inner_text() if li else '')
            if not txt or ':' not in txt:
                continue
            k, v = txt.split(':', 1)
            k, v = k.strip(), _clean(v)
            if k and v and len(k) < 40:
                pairs.setdefault(k, v)
        for dd_el in page.query_selector_all('dt, div[class*="label"]'):
            k = _clean(dd_el.inner_text() if dd_el else '')
            if not k or len(k) > 30:
                continue
            # 尝试找同容器 dd / 下一个兄弟节点
            parent = dd_el.evaluate_handle('(el)=>el.parentElement')
            # 保守：仅当文本形如"键: 值"
            if ':' in k:
                kk, vv = k.split(':', 1)
                pairs.setdefault(kk.strip(), _clean(vv))
    except Exception:
        pass
    return pairs


def _map_value_to_zh(field_zh, raw_val, raw_field):
    """把属性值映射为标准中文（供热/家具/车位等）。"""
    v = _clean(raw_val)
    vl = v.lower()
    if field_zh == '供暖':
        for pat, zh in _HEAT_VALUE_MAP:
            if re.search(pat, v) or re.search(pat, vl):
                return zh
        # 塞语缩写如 CG
        return v
    if field_zh == '家具状态':
        for pat, zh in _FURN_VALUE_MAP:
            if re.search(pat, v) or re.search(pat, vl):
                return zh
        return v if v else '未说明'
    if field_zh == '车位':
        return '有车位' if _AMENITY_KEYS.get(raw_field.lower()) else v
    return v


def _keyword_scan(full_text):
    """对整页文本做关键词扫描，返回 {core补充}/{amenities}/{policy}/{供暖}/{家具} 兜底。

    返回 (extra_std: dict, amenities_zh: list, policy_zh: list)
    """
    tl = full_text.lower()
    extra = {}
    amenities = []
    policy = []

    # 供暖
    for pat, zh in _HEAT_VALUE_MAP:
        if re.search(pat, tl):
            extra.setdefault('供暖', zh)
            break
    # 家具
    if _FURN_POSITIVE.search(tl):
        extra.setdefault('家具状态', '已配家具')
    # 配套
    for word, zh in _AMENITY_KEYS.items():
        if re.search(r'\b' + re.escape(word), tl):
            if zh not in amenities:
                amenities.append(zh)
    # 政策
    if _PET_POS.search(tl) and not _PET_NEG.search(tl):
        policy.append('允许养宠物')
    elif _PET_NEG.search(tl):
        policy.append('不允许养宠物')
    if _DEPOSIT.search(tl):
        policy.append('需缴押金')
    m = _LEASE_MIN.search(full_text)
    if m:
        policy.append('设最短租期')
    if _MOVEIN.search(tl):
        policy.append('可即刻入住' if not any('可即刻' in p for p in policy) else None)
    policy = [p for p in policy if p]
    return extra, amenities, policy


def scrape_detail(page, url, known_item=None):
    """通用详情页抓取（不绑定网站）。

    参数：
      page       — Playwright 已打开的 Page
      url        — 房源详情页 URL
      known_item — 可选的列表页已知信息 dict（价格/面积/片区等），
                   用于在详情页信息缺失时兜底补全。

    返回 dict：
      {
        'url','source','title','image','price','core': {...}, 'attrs': {原生名:值},
        'std_attrs': {标准中文键: 中文值}, 'amenities': [中文...], 'policy': [中文...],
        'description': <原始正文>, 'raw_text': <整页可见文本>,
      }
    """
    known = known_item or {}
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(2500)
    except Exception as e:
        print(f"⚠️ detail_scraper: 打开 {url} 失败: {e}", file=sys.stderr)
        page.goto('about:blank')

    # ---- 1) 标题 / 图片 / og:description ----
    title = known.get('title') or ''
    try:
        og_t = page.query_selector('meta[property="og:title"]')
        if og_t and og_t.get_attribute('content'):
            title = og_t.get_attribute('content')
    except Exception:
        pass
    if not title:
        try:
            t = page.query_selector('h1')
            if t:
                title = _clean(t.inner_text())
        except Exception:
            pass

    image = known.get('image') or ''
    try:
        og_i = page.query_selector('meta[property="og:image"]')
        if og_i and og_i.get_attribute('content'):
            c = og_i.get_attribute('content')
            if 'no-image' not in c and 'kategorije' not in c and 'placeholder' not in c:
                image = c
    except Exception:
        pass

    # ---- 2) 接受 cookie 同意（HaloOglasi 等站点正文默认被 cookie 横幅遮挡）----
    try:
        for btn_sel in ['button[id*=accept]', 'button[class*=accept]', '#didomi-notice-agree-button',
                        'button:has-text("Prihvati")', 'button:has-text("Accept")',
                        'button:has-text("同意")']:
            try:
                b = page.query_selector(btn_sel)
                if b and b.is_visible():
                    b.click()
                    page.wait_for_timeout(1200)
                    break
            except Exception:
                continue
    except Exception:
        pass

    # ---- 2b) 全页可见文本 + 描述 ----
    full_text = ''
    description = ''
    try:
        body = page.query_selector('body')
        if body:
            full_text = _clean(body.inner_text())
    except Exception:
        pass
    # 尽力提取正文描述：优先级 og:description / meta description > JSON-LD > 页面正文容器。
    try:
        for sel in _DESC_SELECTORS:
            el = page.query_selector(sel)
            if not el:
                continue
            if sel.startswith('meta'):
                c = el.get_attribute('content')
                if c:
                    description = _clean(c)
                    # 排除站点全局 SEO 底稿（非本房源描述），继续往下找真正描述
                    if len(description) > 40 and not re.search(r'Tražite oglase|najpovoljniji|posetite nas|搜房源|最优惠', description, re.I):
                        break
            else:
                t = _clean(el.inner_text())
                if len(t) > 40 and not re.search(r'Tražite oglase|najpovoljniji|posetite nas|搜房源|最优惠', t, re.I):
                    description = t
                    break
    except Exception:
        pass
    # JSON-LD 兜底（og:description 也可能缺失时，从结构化数据补描述）
    if not description or len(description) <= 40:
        for it in _extract_jsonld(page):
            cand = it.get('description') or it.get('name') or ''
            if isinstance(cand, str) and len(_clean(cand)) > 40:
                description = _clean(cand)
                break

    # ---- 3) 结构化属性（JSON-LD + 可见键值对）----
    attrs = {}
    for it in _extract_jsonld(page):
        for kk in ('floorSize', 'numberOfRooms', 'address', 'name',
                   'price', 'amenityFeature', 'additionalProperty'):
            pass
    # 通用：JSON-LD 常见字段
    for it in _extract_jsonld(page):
        if it.get('floorSize'):
            attrs.setdefault('面积', str(it.get('floorSize')))
        if it.get('numberOfRooms'):
            attrs.setdefault('户型', str(it.get('numberOfRooms')))
        if it.get('price') or it.get('offers'):
            pr = it.get('price') or (it.get('offers') or {}).get('price')
            if pr:
                attrs.setdefault('价格', str(pr))
        addr = it.get('address')
        if isinstance(addr, dict) and addr.get('addressLocality'):
            attrs.setdefault('区位', str(addr.get('addressLocality')))
        am = it.get('amenityFeature')
        if isinstance(am, list):
            for a in am:
                name = (a.get('name') if isinstance(a, dict) else str(a))
                if name:
                    attrs.setdefault('配套:' + str(name), '有')

    # 可见键值对
    pairs = _collect_keyvalues(page)
    for k, v in pairs.items():
        attrs.setdefault(k, v)

    # ---- 4) 标准化：原生名 → 中文 ----
    std_attrs = {}
    raw_map = {}
    for raw_k, raw_v in attrs.items():
        low = raw_k.lower().strip()
        mapped = None
        for pat, (zh, _m) in _ATTR_FIELD_MAP.items():
            if low == pat or low.startswith(pat):
                mapped = (zh, raw_v)
                break
        if mapped:
            zh, val = mapped
            val_zh = _map_value_to_zh(zh, val, raw_k)
            std_attrs.setdefault(zh, val_zh)
            raw_map[raw_k] = raw_v
        else:
            # 未识别的原生字段也保留进 raw_map，供 AI 参考
            raw_map[raw_k] = raw_v

    # ---- 5) 关键词兜底补全 ----
    extra, amenities, policy = _keyword_scan(full_text + ' ' + _clean(str(image)) + ' ' + _clean(str(description)))
    for k, v in extra.items():
        if k not in std_attrs:
            std_attrs[k] = v
    # 配套去重并入
    for a in amenities:
        if a not in list(std_attrs.values()):
            std_attrs.setdefault(a, '有')
    # 政策去重
    seen = set()
    policy = [p for p in policy if not (p in seen or seen.add(p))]

    # 兜底：用已知信息补齐核心字段
    if not std_attrs.get('面积') and known.get('size'):
        std_attrs['面积'] = f"{known['size']:g} m²"
    if not std_attrs.get('户型') and known.get('structure'):
        std_attrs['户型'] = known['structure']
    if not std_attrs.get('楼层') and known.get('floor'):
        std_attrs['楼层'] = known['floor']
    if known.get('heating'):
        std_attrs.setdefault('供暖', known['heating'])

    # ---- 6) 价格（详情页优先，否则用已知）----
    price = known.get('price')
    try:
        pr_el = page.query_selector('span[data-value], .price-value, [itemprop="price"], .central-feature i')
        if pr_el:
            t = _clean(pr_el.inner_text() if not pr_el.get_attribute('data-value') else pr_el.get_attribute('data-value'))
            m = re.search(r'\d[\d.,]*', t.replace(' ', ''))
            if m:
                price = float(m.group(0).replace(',', '.')) if '.' not in m.group(0).replace(',', '') else None or price
    except Exception:
        pass

    # 发布者
    publisher = known.get('publisher') or ''
    if not publisher:
        if _OWNER_WORDS.search(full_text[:1500]) and not _AGENCY_WORDS.search(full_text[:500]):
            publisher = '个人'
        else:
            publisher = '中介/机构'

    # ---- 7) 汇总供 AI 的原始文本：正文 + meta 描述 + JSON-LD（多重兜底，确保有真实内容）----
    # 即使正文被 cookie 遮挡，og:description / meta description / JSON-LD 也含真实房源信息。
    meta_desc = ''
    try:
        for msel in ['meta[property="og:description"]', 'meta[name="description"]']:
            m = page.query_selector(msel)
            if m and m.get_attribute('content'):
                meta_desc += ' ' + _clean(m.get_attribute('content'))
    except Exception:
        pass
    jsonld_text = ' '.join(_clean(str(v)) for it in _extract_jsonld(page)
                           for v in [it.get('description'), it.get('name'), it.get('headline')] if v)
    combined_text = ' '.join([full_text, meta_desc, jsonld_text])
    combined_text = re.sub(r'\s+', ' ', combined_text).strip()

    return {
        'url': url,
        'source': known.get('source') or '未知来源',
        'title': _clean(title),
        'image': image,
        'price': price,
        'publisher': publisher,
        'core': {k: std_attrs.get(k, '') for k in ('面积', '户型', '楼层', '供暖', '家具状态', '装修状态')},
        'attrs': raw_map,           # 原生字段名 → 值（供 AI）
        'std_attrs': std_attrs,     # 标准中文键 → 中文值
        'amenities': policy + [a for a in amenities],  # 合并（政策+配套均列标签）
        'policy': policy,
        'description': description,
        'raw_text': combined_text[:12000],
    }
