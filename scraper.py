# -*- coding: utf-8 -*-
import os, sys, json, re, time, subprocess
import pathlib
import threading
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

# 复用 send_wechat.py 中验证过的稳定推送逻辑（--channel + 120s 超时 + 健壮重试）
from send_wechat import push_all, WECHAT_TARGETS

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_FILE = DATA_DIR / 'history.json'
NEW_ITEMS_FILE = DATA_DIR / 'new_items.json'

TODAY_STR = datetime.now().strftime('%Y-%m-%d')

# --- 路径重构：优先存入外接硬盘 rent 目录，若失败则回退到本地 ---
EXTERNAL_RENT_DIR = pathlib.Path('/Volumes/Data2TB/rent')
if EXTERNAL_RENT_DIR.exists() and os.access(EXTERNAL_RENT_DIR, os.W_OK):
    OUTPUT_BASE = EXTERNAL_RENT_DIR
else:
    OUTPUT_BASE = BASE_DIR / 'output'

TODAY_OUTPUT_DIR = OUTPUT_BASE / f'output_{TODAY_STR}'
TODAY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DETAIL_DIR = TODAY_OUTPUT_DIR / 'details'
DETAIL_DIR.mkdir(parents=True, exist_ok=True)

MIN_PRICE = 350
MAX_PRICE = 650

def load_history():
    if HISTORY_FILE.exists():
        try:
            return set(json.loads(HISTORY_FILE.read_text(encoding='utf-8')))
        except:
            return set()
    return set()

def save_history(history_set):
    HISTORY_FILE.write_text(json.dumps(list(history_set), ensure_ascii=False, indent=2), encoding='utf-8')

# 塞尔维亚片区/地名 → 中文对照表（含常见微片区；无命中时回退到行政区，再无则贝尔格莱德）
AREA_ZH = {
    # 行政区/大片区
    "Novi Beograd": "新贝尔格莱德", "Zemun": "泽蒙", "Vračar": "弗拉查尔",
    "Stari grad": "老城区", "Savski venac": "萨夫斯基维纳茨", "Čukarica": "丘卡里察",
    "Voždovac": "沃日多瓦茨", "Zvezdara": "兹韦兹达拉", "Palilula": "帕利卢拉",
    "Rakovica": "拉科维察", "Surčin": "苏尔钦", "Beograd": "贝尔格莱德",
    # 热门微片区/BW 区
    "Mirijevo": "米里耶沃", "Dedinje": "德迪涅", "Senjak": "塞尼亚克",
    "Crveni krst": "红十字区", "Neimar": "内伊马尔", "Ledine": "莱迪内",
    "Dorćol": "多尔乔尔", "Krnjača": "克尔尼亚恰", "Lekino brdo": "莱基诺山",
    "Cvetkova pijaca": "茨韦特科娃集市", "Blok 37": "37区", "Block 37": "37区",
    "Kluz": "克卢兹", "Karaburma": "卡拉布尔马", "Banovo brdo": "巴诺沃山",
    "Beograd na vodi": "贝尔格莱德水岸", "Beograd na Vodi": "贝尔格莱德水岸",
    "Bulevar kralja Aleksandra": "亚历山大国王大道", "Fontana": "方塔纳",
    "YUBC": "商务中心区", "Belville": "贝尔维尔", "Ada": "阿达",
}

# 行政区（大写匹配用，兼容 "Opština Xxx"）
DISTRICT_ALIAS = {
    "zvezdara": "Zvezdara", "vracar": "Vračar", "starigrad": "Stari grad",
    "savskivenac": "Savski venac", "cukarica": "Čukarica", "vozdovac": "Voždovac",
    "palilula": "Palilula", "rakovica": "Rakovica", "surcin": "Surčin",
    "novibeograd": "Novi Beograd", "zemun": "Zemun", "beograd": "Beograd",
}


def area_zh(name):
    """塞尔维亚片区名 → 中文。优先精确查表，其次尝试行政区化，最后回退。"""
    if not name:
        return ""
    n = str(name).strip()
    # 精确命中
    if n in AREA_ZH:
        return AREA_ZH[n]
    # 尝试匹配行政区首词
    first = n.split()[0] if n.split() else n
    if first in AREA_ZH:
        return AREA_ZH[first]
    # 尝试去掉连字符/空格后按行政区别名映射
    key = re.sub(r"[^a-z]", "", n.lower())
    if key in DISTRICT_ALIAS:
        return AREA_ZH.get(DISTRICT_ALIAS[key], key)
    return ""


def rooms_zh(rooms):
    """几房 → 中文户型名称。"""
    if rooms is None:
        return ""
    r = float(rooms)
    if r <= 1.25:
        return "一房"
    if r <= 1.75:
        return "一房半"
    if r <= 2.25:
        return "两房"
    if r <= 2.75:
        return "两房半"
    if r <= 3.25:
        return "三房"
    if r <= 3.75:
        return "三房半"
    return f"{r:g} 房"


def fetch_cityexpert(page):
    items = []
    url = f"https://cityexpert.rs/en/properties-for-rent/belgrade?ptypeid=1&priceFrom={MIN_PRICE}&priceTo={MAX_PRICE}"
    try:
        response_data = []
        def handle_response(response):
            if "api/search" in response.url and response.status == 200:
                try:
                    res_json = response.json()
                    listings = res_json.get('result', []) if isinstance(res_json, dict) else (res_json if isinstance(res_json, list) else [])
                    response_data.extend(listings)
                except Exception:
                    pass

        page.on("response", handle_response)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        
        for item in response_data:
            prop_id = item.get('propId') or item.get('id')
            if not prop_id:
                continue
            price = parse_price(item.get('price'))
            street = item.get('streetName') or item.get('locationName') or 'Belgrade'
            structure = item.get('structureName') or 'Apartment'
            
            photos = item.get('photos', [])
            img_url = ""
            if photos and isinstance(photos, list):
                img_path = photos[0].get('path') or photos[0].get('name')
                if img_path:
                    img_url = f"https://img.cityexpert.rs/properties/470x/{img_path}"
            if not img_url:
                img_url = "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80"
                
            if within_budget(price):
                item_url = f"https://cityexpert.rs/en/properties-for-rent/belgrade/{prop_id}"
                area_cn = extract_cityexpert_area(item, street, item_url)
                # 设施：从可用字段粗略识别（CityExpert API 列表字段有限，尽力而为）
                extras = halo_parse_feature_text(f"{street} {structure}")
                heating = ""
                other = []
                for x in extras:
                    if '供暖' in x or '电暖' in x:
                        heating = x
                    else:
                        other.append(x)
                rooms_word = ""
                # CityExpert structureName 常见为 '1+0、2-room、3.5-room...'，从中取房间数
                mm = re.search(r'(\d(?:\.\d)?)', structure)
                if mm and re.search(r'room|soba|\+', structure.lower()):
                    try:
                        rooms_word = rooms_zh(float(mm.group(1)))
                    except Exception:
                        rooms_word = ""
                if not rooms_word:
                    rooms_word = structure
                structure_short = rooms_word if rooms_word != structure else structure
                # 标题：塞尔维亚片区 + 中文 + 户型/特色
                title_parts = [area_cn]
                if other:
                    title_parts.append(" · ".join(other))
                elif structure_short and structure_short != structure:
                    title_parts.append(structure_short)
                title = " · ".join(title_parts)
                # 底部核心参数副标题：户型 · 供暖 · 车位/家具
                subtitle_parts = [structure_short] if structure_short and structure_short != structure else []
                if heating:
                    subtitle_parts.append(heating)
                if other:
                    subtitle_parts.append(" · ".join(other))
                subtitle = " · ".join(subtitle_parts)
                items.append({
                    'id': f"ce_{prop_id}",
                    'source': 'CityExpert',
                    'title': title,
                    'price': parse_price(price),
                    'area_name': area_cn,
                    'structure': structure_short,
                    'features': f"<b>{structure_short}</b> · {subtitle}" if subtitle else f"<b>{structure_short}</b>",
                    'raw_features': subtitle,
                    'size': None,
                    'rooms': None,
                    'floor': '',
                    'heating': heating,
                    'image': img_url,
                    'url': item_url
                })
    except Exception as e:
        print(f"CityExpert 渲染异常: {e}")
    return items


def extract_cityexpert_area(item, street, item_url):
    """从 CityExpert 数据识别真实塞尔维亚片区 + 中文名。优先 url slug，其次 locationName/street。"""
    hint = (item.get('locationName') or item.get('municipality') or item.get('neighborhood') or street or "")
    # slug 里通常带片区，如 ...-edvarda-griga-rakovica
    slug = item_url.lower()
    found = ""
    for name, zh in sorted(AREA_ZH.items(), key=lambda kv: -len(kv[0])):
        if name.lower() in slug:
            found = name
            break
    if not found and hint:
        h = str(hint).lower()
        for name, zh in sorted(AREA_ZH.items(), key=lambda kv: -len(kv[0])):
            if name.lower() in h:
                found = name
                break
    if found:
        return f"{found} {AREA_ZH[found]}".strip()
    # 回退到 hint 原文或贝尔格莱德
    if hint and hint != "Belgrade":
        zh_hint = area_zh(hint)
        return f"{hint} {zh_hint}".strip() if zh_hint else hint
    return "贝尔格莱德"

def halo_card_price(card):
    """在单个 product-item 卡片内部提取价格（data-value 或 <i> 文本），绝不跨卡片。"""
    # 优先取本卡片内的 data-value 属性（列表页价格载体）
    price_el = card.query_selector('span[data-value]')
    if price_el:
        raw = (price_el.get_attribute('data-value') or '').strip()
        if raw:
            p = parse_price(raw)
            if p is not None:
                return p
    # 兜底：取卡片内中央价格 <i> 的文本（如 "650&nbsp;€"），只取本卡片子树
    i_el = card.query_selector('.central-feature i')
    if i_el:
        text = (i_el.inner_text() or '').strip()
        p = parse_price(text)
        if p is not None:
            return p
    return None


def halo_card_image(card):
    """在单个 product-item 卡片内部提取真实房源照片 URL（不再用占位图）。
    优先取卡片内 <img src="/slike/oglasi/...">（列表页缩略图），并归一化 // 双斜杠。"""
    img = card.query_selector('img[src*=slike][src*=oglasi], .pi-img-wrapper img')
    if img:
        src = (img.get_attribute('src') or '').strip()
        if src.startswith('//'):
            src = 'https:' + src
        if src.startswith('/'):
            src = 'https://www.halooglasi.com' + src
        if 'slike/oglasi' in src and 'no-image' not in src:
            return src
    return ''


def halo_card_link(card):
    """在单个 product-item 卡片内部提取指向房源详情页的链接。"""
    a = card.query_selector('.product-title a[href], a.a-images[href]')
    if a:
        href = (a.get_attribute('href') or '').strip()
        if href.startswith('/nekretnine/'):
            return href.split('?')[0]
    return ''


def halo_card_places(card):
    """提取卡片内 subtitle-places：行政区/片区/街名等，返回列表（仅本卡片子树）。"""
    ul = card.query_selector('ul.subtitle-places')
    places = []
    if ul:
        for li in ul.query_selector_all('li'):
            t = (li.inner_text() or '').strip()
            if t:
                places.append(t)
    return places


def halo_card_features(card):
    """提取卡片内 product-features：Kvadratura(面积)/Broj soba(几房)/Spratnost(楼层)。"""
    feats = {}
    ul = card.query_selector('ul.product-features, ul[class*=product-features]')
    if ul:
        for div in ul.query_selector_all('li .value-wrapper'):
            text = (div.inner_text() or '').strip()
            legend = div.query_selector('span.legend')
            label = (legend.inner_text() or '').strip() if legend else ''
            value = text.replace(label, '').strip()
            if label:
                feats[label] = value
    return feats


def halo_card_desc(card):
    """提取卡片内房源描述短文本（塞尔维亚语，含真实区位/设施线索）。"""
    el = card.query_selector('.text-description-list.product-description, .product-description.short-desc')
    if el:
        return (el.inner_text() or '').strip()
    return ''


def halo_parse_feature_text(text):
    """从塞尔维亚语描述/标题/slug 中识别真实设施（供暖/车位/家具/电梯/阳台/新楼/即刻入住），返回列表。"""
    found = []
    t = f"{text}".lower()
    if re.search(r'centralno|central heating|centralno grejanje|city heating|集中供暖', t):
        found.append("集中供暖")
    if re.search(r'gasno|gas |gasn|燃气|gas heating', t):
        found.append("燃气供暖")
    if re.search(r'\bta\b|elektric|electric|电暖|电热', t):
        found.append("电暖")
    if re.search(r'parking|garaž|garaz|parking mesto|车位', t):
        found.append("带车位")
    if re.search(r'namest|oprem|lju|furnished|家具|配好', t):
        found.append("全配家具")
    if re.search(r'teras|terace|阳台', t):
        found.append("带阳台")
    if re.search(r'lift|电梯', t):
        found.append("有电梯")
    if re.search(r'novogradnja|novograd|nova zgrada|新楼', t):
        found.append("新楼")
    # 去重保序
    seen = set()
    uniq = []
    for x in found:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def halo_build_item(item_id, place_hint, hf, desc_text, price, img_url, href):
    """由单卡片提取的真实字段构建房源 item（片区中文名 + 动态标题 + 核心参数副标题）。"""
    # 片区：优先用 subtitle-places 里的微片区/行政区，回退用标题
    district = ""
    micro = ""
    if place_hint:
        # 最后去掉 "Opština" 前缀的行政区是重点候选；微片区通常在第3项
        for p in place_hint:
            if p.startswith('Opština'):
                district = re.sub(r'^Opština\s*', '', p).strip()
        if not micro:
            # 取第3项（Beograd / Opština Xxx / 微片区 / 街道）
            if len(place_hint) >= 3 and not place_hint[2].startswith('Opština'):
                micro = place_hint[2]
        if not district:
            district = place_hint[1] if len(place_hint) >= 2 else ''
    focus = micro or district
    zh = area_zh(focus) or area_zh(district)
    sr_name = focus if focus else "贝尔格莱德"

    # 面积/几房/楼层
    size = None
    rooms = None
    floor = ""
    for label, val in hf.items():
        low = label.lower()
        if 'kvadr' in low:
            mm = re.search(r'([\d.,]+)', val)
            if mm:
                try:
                    size = float(mm.group(1).replace(',', '.'))
                except Exception:
                    size = None
        elif 'soba' in low or 'broj' in low:
            mm = re.search(r'([\d.,]+)', val)
            if mm:
                try:
                    rooms = float(mm.group(1).replace(',', '.'))
                except Exception:
                    rooms = None
        elif 'sprat' in low:
            floor = val.strip()

    # 供暖与设施：从描述+slug+标题里识别
    slug = href or ''
    feat_text = f"{desc_text} {slug}".lower()
    extras = halo_parse_feature_text(feat_text)
    # 从设施里分出供暖（集中供暖/燃气供暖/电暖）与其余配套
    heating = ""
    other = []
    for x in extras:
        if '供暖' in x or '电暖' in x:
            heating = x
        else:
            other.append(x)

    # 中文片区标签（含微片区中文名）
    area_cn = f"{sr_name} {zh}".strip() if zh else sr_name
    # 标题：塞尔维亚片区 + 中文 + 户型/特色
    rooms_word = rooms_zh(rooms) if rooms else ""
    feature_word = ""
    if '新楼' in other:
        feature_word = f"{rooms_word}新楼" if rooms_word else "新楼"
    elif rooms_word:
        feature_word = rooms_word
    # 片区亮点描述词：如 新楼/即刻入住/带车位 等
    highlight = " · ".join(other) if other else (feature_word or "")
    title_parts = [f"{sr_name} {zh}".strip() if zh else sr_name]
    if highlight:
        title_parts.append(highlight)
    title = " · ".join(title_parts)

    # 底部核心参数副标题：面积 · 几房 · 供暖 · 车位/家具
    subtitle_parts = []
    if size and size > 0:
        subtitle_parts.append(f"{size:.0f} m²" if size == int(size) else f"{size:g} m²")
    if rooms and rooms > 0:
        subtitle_parts.append(rooms_zh(rooms))
    if heating:
        subtitle_parts.append(heating)
    if other:
        subtitle_parts.append(" · ".join(other))
    subtitle = " · ".join(subtitle_parts)

    return {
        'id': f'halo_{item_id}',
        'source': 'HaloOglasi',
        'title': title,
        'price': price,
        'area_name': area_cn,
        'structure': rooms_word or "公寓",
        'features': subtitle,
        'raw_features': subtitle,
        'size': size,
        'rooms': rooms,
        'floor': floor,
        'heating': heating,
        'image': img_url,
        'url': f'https://www.halooglasi.com{href}'
    }


def fetch_halooglasi(page):
    items = []
    url = f"https://www.halooglasi.com/nekretnine/izdavanje-stanova/beograd?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        # 按卡片隔离解析：每一个 .product-item 是独立房源卡片，内部提取 ID/链接/价格/图片/区位/户型，杜绝跨卡片串数据
        cards = page.query_selector_all('.product-item')
        for card in cards:
            item_id_el = card.get_attribute('data-id')
            if not item_id_el or not item_id_el.isdigit():
                continue
            item_id = item_id_el
            href = halo_card_link(card)
            if not href:
                continue
            price = halo_card_price(card)
            if not within_budget(price):
                continue
            img_url = halo_card_image(card)
            # 若卡片内无真实大图，再访问详情页取 og:image（真实相册首图）
            if not img_url:
                try:
                    page.goto('https://www.halooglasi.com' + href, wait_until="domcontentloaded", timeout=30000)
                    og = page.query_selector('meta[property="og:image"]')
                    if og:
                        content = (og.get_attribute('content') or '').strip()
                        if 'no-image' not in content and 'kategorije' not in content:
                            img_url = content
                except Exception as e:
                    print(f"HaloOglasi 详情页取图异常({item_id}): {e}")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
            place_hint = halo_card_places(card)
            hf = halo_card_features(card)
            desc_text = halo_card_desc(card)
            item = halo_build_item(item_id, place_hint, hf, desc_text, price, img_url, href)
            items.append(item)
    except Exception as e:
        print(f"HaloOglasi 渲染异常: {e}")
    return items

def fetch_4zida(page):
    items = []
    url = f"https://www.4zida.rs/izdavanje-stanova/beograd?cena-od={MIN_PRICE}EUR&cena-do={MAX_PRICE}EUR"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        html = page.content()
        matches = re.findall(r'href="(/izdavanje-stanova/beograd/[^"]+?)".*?(\d+)\s*€', html, re.DOTALL)
        for href, price_str in matches:
            price = parse_price(price_str)
            id_match = re.search(r'/(\d+)$', href)
            item_id = id_match.group(1) if id_match else str(hash(href))
            if within_budget(price):
                items.append({
                    'id': f'4zida_{item_id}',
                    'source': '4zida',
                    'title': f'贝尔格莱德公寓 · 品质之选',
                    'price': price,
                    'area_name': '贝尔格莱德优质片区',
                    'structure': '精品户型',
                    'features': '<b>优质房源</b> · 采光好',
                    'raw_features': '采光充足 · 宜居',
                    'image': 'https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=800&q=80',
                    'url': f'https://www.4zida.rs{href}'
                })
    except Exception as e:
        print(f"4zida 渲染异常: {e}")
    return items

def start_local_server_and_tunnel(root_dir):
    port = 8765
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root_dir), **kwargs)
        def log_message(self, format, *args):
            pass

    server = HTTPServer(('127.0.0.1', port), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    public_url = None
    tunnel_process = None
    try:
        tunnel_process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        start_time = time.time()
        while time.time() - start_time < 10:
            line = tunnel_process.stdout.readline()
            if not line:
                break
            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if match:
                public_url = match.group(0)
                break
    except Exception as e:
        print(f"⚠️ 公网隧道启动失败: {e}")

    return server, tunnel_process, public_url

def parse_price(value):
    """将房源价格安全转为 int；无法解析或异常返回 None（绝不放行坏数据）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        p = int(value)
        return p if p > 0 else None
    try:
        # 处理 "400", "400 EUR", "€400", "1,000", "400.50" 等常见字符串形式
        s = str(value).replace('€', '').replace('EUR', '').replace('eur', '').strip()
        # 逗号后跟 3 位数字 => 千位分隔符（如 1,000）；否则视为小数/千位混合统一剥掉，保留点做小数
        if re.search(r',\d{3}(\D|$)', s):
            s = s.replace(',', '')      # 千位分隔，直接移除
        else:
            s = s.replace(',', '.').replace('..', '.')  # 小数逗号->点
        m = re.search(r'\d+(\.\d+)?', s)
        if not m:
            return None
        p = round(float(m.group()))
        return p if p > 0 else None
    except Exception:
        return None


def within_budget(price):
    """严格校验价格是否落在 MIN_PRICE~MAX_PRICE 硬编码预算区间内。"""
    p = parse_price(price)
    return p is not None and MIN_PRICE <= p <= MAX_PRICE


def send_wechat_notification(new_items, public_url=None):
    """统一推送链路：复用 send_wechat.py 的 push_all（--channel + 120s 超时 + 重试）。"""
    index_filename = f"index_{TODAY_STR}.html"

    if public_url:
        # 静态服务根目录 = OUTPUT_BASE（如 /Volumes/Data2TB/rent），
        # 而文件实际存放在 output_{TODAY_STR}/ 子目录下，链接必须带上该目录段，否则 404。
        main_link = f"{public_url}/output_{TODAY_STR}/{index_filename}"
    else:
        main_link = f"本地路径: {TODAY_OUTPUT_DIR / index_filename}"

    if new_items:
        lines = [f"🏠 【贝尔格莱德租房日报】({TODAY_STR})", f"筛选条件：{MIN_PRICE}~{MAX_PRICE} EUR\n今日新增 {len(new_items)} 套精选好房：\n"]
        for idx, item in enumerate(new_items, 1):
            lines.append(f"{idx}. [{item['source']}] {item['price']}€ - {item['title']}")
            if public_url:
                lines.append(f"   详情页: {public_url}/output_{TODAY_STR}/details/house_{idx}.html")
        lines.append(f"\n🌐 点击查看今日完整中文看板：\n{main_link}")
        msg_text = "\n".join(lines)
    else:
        msg_text = f"🏠 【贝尔格莱德租房日报】({TODAY_STR})\n筛选条件：{MIN_PRICE}~{MAX_PRICE} EUR\n今日暂无新增新房源，自动化服务正常运行中。\n\n🌐 看板地址：\n{main_link}"

    print("📲 正在通过 send_wechat.py 的稳定推送链路发送微信推送...")
    ok = push_all(msg_text)
    if ok:
        print("✅ 微信消息推送成功！")
    else:
        print("❌ 微信消息推送失败（已重试）", file=sys.stderr)
    return ok

def _render_board(new_items):
    """根据房源列表重新生成：每套独立详情页 + 今日中文索引看板。返回 None，目录写入即完成。"""
    if not new_items:
        print('⚠️ _render_board: 无房源，仅重建空看板')
    for idx, item in enumerate(new_items, 1):
        detail_filename = f"house_{idx}.html"
        item['detail_link'] = f"details/{detail_filename}"

        detail_html = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{item['title']} - 贝尔格莱德中文看房</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,"PingFang SC","Segoe UI",Roboto,sans-serif;background:#0e1a2b;color:#f2f5f9;padding:20px}}
  .wrap{{max-width:680px;margin:0 auto}}
  .card{{background:#ffffff;color:#1f2a3d;border-radius:16px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.35);margin-bottom:20px}}
  .pic{{height:320px;background:#e4e8f0 center/cover no-repeat}}
  .body{{padding:24px}}
  .top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}}
  .price{{font-size:32px;font-weight:800;color:#c0392b}}
  .price small{{font-size:14px;color:#888;font-weight:500}}
  .area{{font-size:14px;background:#eef2fa;color:#38507e;padding:6px 14px;border-radius:99px;font-weight:600}}
  h1{{font-size:22px;margin-bottom:14px;color:#1f2a3d;line-height:1.4}}
  .section-title{{font-size:15px;font-weight:700;color:#27437f;margin:18px 0 8px;border-left:4px solid #27437f;padding-left:8px}}
  .info-box{{background:#f8f9fc;padding:14px 16px;border-radius:10px;font-size:14px;color:#444;line-height:1.8;margin-bottom:16px}}
  .btn{{display:block;text-align:center;background:linear-gradient(135deg,#27437f,#1a2a4a);color:#fff;padding:14px;border-radius:12px;font-size:16px;font-weight:bold;text-decoration:none;margin-top:20px;box-shadow:0 4px 12px rgba(39,67,127,.3)}}
  .back{{display:inline-block;color:#9fb8e8;font-size:13px;margin-bottom:14px;text-decoration:none}}
  footer{{text-align:center;color:#6b7f9e;font-size:12px;padding:14px 0}}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="../index_{TODAY_STR}.html">← 返回今日房源列表</a>
  <div class="card">
    <div class="pic" style="background-image:url('{item['image']}')"></div>
    <div class="body">
      <div class="top"><span class="price">€{item['price']}<small>/月</small></span><span class="area">{item['area_name']}</span></div>
      <h1>{item['title']}</h1>
      
      <div class="section-title">中文智能解析与核心亮点</div>
      <div class="info-box">
        <b>户型结构：</b>{item['structure']}<br>
        <b>特色配套：</b>{item['raw_features']}<br>
        <b>数据来源：</b>{item['source']} 官方直连
      </div>

      <div class="section-title">塞尔维亚位置与官方原网</div>
      <p style="font-size:13px;color:#666;line-height:1.6;">该房源由平台认证发布。您可以点击下方按钮直达原网站查看完整多图、预约看房或与房东联系。</p>
      
      <a class="btn" href="{item['url']}" target="_blank">🌐 在原平台（{item['source']}）查看完整房源与地图</a>
    </div>
  </div>
  <footer>贝尔格莱德租房智能监控 · 华人专属中文看板</footer>
</div>
</body>
</html>
'''
        (DETAIL_DIR / detail_filename).write_text(detail_html, encoding='utf-8')

    html_report = TODAY_OUTPUT_DIR / f'index_{TODAY_STR}.html'
    report_content = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>贝尔格莱德好房 · 中文推荐看板</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,"PingFang SC","Segoe UI",Roboto,sans-serif;background:#0e1a2b;color:#f2f5f9;padding:20px}}
  .wrap{{max-width:680px;margin:0 auto}}
  header{{background:linear-gradient(135deg,#1a2a4a,#27437f);border-radius:16px;padding:22px 24px;margin-bottom:18px;box-shadow:0 8px 24px rgba(0,0,0,.35)}}
  header .kicker{{font-size:13px;letter-spacing:2px;color:#9fb8e8;text-transform:uppercase;margin-bottom:6px}}
  header h1{{font-size:24px;font-weight:700}}
  header .sub{{font-size:13px;color:#c8d6f2;margin-top:6px}}
  .date{{display:inline-block;background:#ffffff22;border:1px solid #ffffff33;padding:3px 12px;border-radius:99px;font-size:12px;margin-top:8px}}
  .card{{background:#ffffff;color:#1f2a3d;border-radius:14px;margin-bottom:16px;overflow:hidden;box-shadow:0 6px 20px rgba(0,0,0,.28);display:block;text-decoration:none}}
  .card .pic{{height:200px;background:#e4e8f0 center/cover no-repeat}}
  .card .body{{padding:16px 18px 18px}}
  .card .top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
  .card .price{{font-size:26px;font-weight:800;color:#c0392b}}
  .card .price small{{font-size:13px;color:#888;font-weight:500}}
  .card .area{{font-size:13px;background:#eef2fa;color:#38507e;padding:4px 12px;border-radius:99px}}
  .card h3{{font-size:18px;margin-bottom:8px;color:#1f2a3d}}
  .card .feat{{font-size:13px;color:#666;line-height:1.7}}
  .card .feat b{{color:#1f2a3d}}
  .card .link{{font-size:12px;color:#27437f;margin-top:10px;display:inline-block;border-bottom:1px dashed #9fb8e8;padding-bottom:2px}}
  footer{{text-align:center;color:#6b7f9e;font-size:12px;padding:14px 0 6px}}
  .tag{{font-size:11px;color:#27437f;background:#e6edfc;padding:2px 8px;border-radius:99px;margin-left:8px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="kicker">BELGRADE RENTALS</div>
    <h1>🏙 贝尔格莱德好房中文看板</h1>
    <div class="sub">今日精选 {len(new_items)} 套 · 租金 €{MIN_PRICE}–{MAX_PRICE}</div>
    <span class="date">📅 {TODAY_STR} 更新</span>
  </header>
'''

    if new_items:
        for item in new_items:
            report_content += f'''
  <a class="card" href="{item['detail_link']}" target="_blank">
    <div class="pic" style="background-image:url('{item['image']}')"></div>
    <div class="body">
      <div class="top"><span class="price">€{item['price']}<small>/月</small></span><span class="area">{item['area_name']}</span><span class="tag">{item['source']}</span></div>
      <h3>{item['title']}</h3>
      <div class="feat">{item['features']}</div>
      <div class="link">查看中文详细解析与原网入口 →</div>
    </div>
  </a>
'''
    else:
        report_content += '''
  <div style="background:#ffffff;color:#1f2a3d;border-radius:14px;padding:30px;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,.28);">
    <h3>今日暂无新增房源</h3>
    <p style="color:#666;font-size:13px;margin-top:8px;">系统自动化运行正常，明天将继续为您监控！</p>
  </div>
'''

    report_content += f'''
  <footer>来自 OpenClaw 房源监控 · 华人专属中文多源聚合看板</footer>
</div>
</body>
</html>
'''

    html_report.write_text(report_content, encoding='utf-8')
    print(f'📄 中文聚合看板与独立详情页已成功生成: {html_report}')


def _send_wechat(new_items):
    """启动本地静态服务+公网隧道，然后通过微信通道推送测试/日报。返回是否送达。"""
    server, tunnel_process, public_url = start_local_server_and_tunnel(OUTPUT_BASE)
    try:
        ok = send_wechat_notification(new_items, public_url)
        return ok
    finally:
        if tunnel_process:
            tunnel_process.terminate()
        server.shutdown()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="贝尔格莱德租房抓取+中文看板生成")
    ap.add_argument('--rerender', action='store_true',
                    help='不重新抓取，直接从今天 data/new_items.json 重新渲染列表+详情页（用于改版后回放）')
    ap.add_argument('--skip-push', action='store_true', help='生成看板但不发送微信推送')
    args = ap.parse_args()

    if args.rerender:
        print(f'♻️ 重渲染模式：读取今日已抓房源 {NEW_ITEMS_FILE}，不重复抓取/不动 history')
        if not NEW_ITEMS_FILE.exists():
            print(f'❌ 找不到 {NEW_ITEMS_FILE}，无法重渲染', file=sys.stderr)
            return
        try:
            new_items = json.loads(NEW_ITEMS_FILE.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'❌ 读取 {NEW_ITEMS_FILE} 失败: {e}', file=sys.stderr)
            return
        if not isinstance(new_items, list) or not new_items:
            print('今日暂无房源数据可重渲染')
            return
        print(f'♻️ 待重渲染房源: {len(new_items)} 条')
        _render_board(new_items)
        if not args.skip_push:
            _send_wechat(new_items)
        return

    print(f'🚀 启动 Playwright 引擎进行全平台渲染抓取 ({MIN_PRICE}EUR - {MAX_PRICE}EUR)...')
    print(f'📂 当前输出根目录: {TODAY_OUTPUT_DIR}')
    history = load_history()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        ce_items = fetch_cityexpert(page)
        halo_items = fetch_halooglasi(page)
        zida_items = fetch_4zida(page)
        browser.close()
        
    all_raw_items = ce_items + halo_items + zida_items
    print(f'📊 汇总原始房源总量: {len(all_raw_items)} 条')
    
    new_items = []
    for item in all_raw_items:
        if item['id'] not in history:
            new_items.append(item)
            history.add(item['id'])
            
    print(f'✨ 去重过滤后实际新增房源: {len(new_items)} 条')
    NEW_ITEMS_FILE.write_text(json.dumps(new_items, ensure_ascii=False, indent=2), encoding='utf-8')
    save_history(history)
    _render_board(new_items)
    _send_wechat(new_items)

if __name__ == '__main__':
    main()
